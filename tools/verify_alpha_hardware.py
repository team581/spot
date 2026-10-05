"""Read-only checks of an already-running alpha daemon; never opens camera devices.

Run on either the Mac or Jetson. Counter deltas distinguish failures during this
check from historical failures. A daemon restart invalidates the run; retry once
the deployment has finished. Throughput is measured, not compared to requested FPS.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import urlopen

COUNTERS = ("captured", "detected", "capture_failures", "decode_failures", "reconnects",
            "overwritten_before_processing", "result_queue_drops", "driver_sequence_gaps",
            "timestamp_discontinuities")


def _finite_vector(value, length):
    return (isinstance(value, list) and len(value) == length
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in value))


def telemetry_failures(camera, expected_ids=()):
    """Check relationships in one published result, without inventing pose ground truth."""
    failures = []
    if not camera.get("fresh"):
        failures.append("stale_frame")
    if camera.get("calibration_error") or camera.get("counters", {}).get("configuration_error"):
        failures.append("configuration_error")
    if camera.get("restart_required"):
        failures.append("calibration_restart_required")
    telemetry = camera.get("telemetry", {})
    tags = telemetry.get("tags", [])
    if not tags:
        failures.append("no_visible_tag")
    ids = [tag.get("id") for tag in tags]
    if len(set(ids)) != len(ids):
        failures.append("duplicate_tag_ids")
    if expected_ids and not set(expected_ids).issubset(ids):
        failures.append("expected_tag_missing")
    for tag in tags:
        corners = tag.get("corners", [])
        if not (isinstance(corners, list) and len(corners) == 4
                and all(_finite_vector(point, 2) for point in corners)):
            failures.append("invalid_corners")
        if not isinstance(tag.get("hamming"), int) or tag["hamming"] < 0:
            failures.append("invalid_hamming")
    pose = telemetry.get("pose")
    candidates = telemetry.get("candidates", [])
    if not pose:
        failures.append("missing_robot_pose")
    for candidate in [*candidates, *([pose] if pose else [])]:
        if not _finite_vector(candidate.get("translation"), 3):
            failures.append("invalid_translation")
        quaternion = candidate.get("quaternion")
        if not _finite_vector(quaternion, 4):
            failures.append("invalid_quaternion")
        elif abs(sum(x * x for x in quaternion) - 1) > 1e-5:
            failures.append("unnormalized_quaternion")
        error = candidate.get("error_px")
        if not isinstance(error, (int, float)) or not math.isfinite(error) or error < 0:
            failures.append("invalid_reprojection_error")
        if not candidate.get("tag_ids") or not set(candidate["tag_ids"]).issubset(ids):
            failures.append("pose_uses_unobserved_tags")
    if pose and not candidates:
        failures.append("missing_camera_candidates")
    elif pose and "invalid_reprojection_error" not in failures:
        if abs(pose["error_px"] - min(candidate["error_px"] for candidate in candidates)) > 1e-6:
            failures.append("wrong_selected_candidate")
    for key in ["detect_ms", "solve_ms"]:
        value = telemetry.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            failures.append(f"invalid_{key}")
    return sorted(set(failures))


def evaluate_samples(samples, elapsed_s, previews, *, expected_cameras=(), expected_ids=(),
                     min_valid_fraction=.9, min_detect_fps=1.):
    """Evaluate captured telemetry; every requested camera must remain observable."""
    if len(samples) < 2 or elapsed_s <= 0:
        raise ValueError("at least two samples and positive elapsed time are required")
    by_sample = [{camera["id"]: camera for camera in sample["cameras"] if camera["enabled"]}
                 for sample in samples]
    ids = set(expected_cameras) or set(by_sample[0])
    if not ids:
        raise ValueError("no enabled cameras")
    results = {}
    for camera_id in sorted(ids):
        rows = [sample.get(camera_id) for sample in by_sample]
        failures, warnings = [], []
        if any(row is None for row in rows):
            results[camera_id] = {"passed": False, "failures": ["camera_missing"], "warnings": []}
            continue
        problems = [telemetry_failures(row, expected_ids) for row in rows]
        valid_fraction = sum(not problem for problem in problems) / len(rows)
        if valid_fraction < min_valid_fraction:
            failures.append("invalid_telemetry_fraction")
        # Check every interval: a mid-run restart must not be hidden by later recovery.
        reset = any(after["counters"].get(key, 0) < before["counters"].get(key, 0)
                    for before, after in zip(rows, rows[1:]) for key in COUNTERS)
        if reset:
            failures.append("daemon_or_counter_reset")
        deltas = {key: rows[-1]["counters"].get(key, 0) - rows[0]["counters"].get(key, 0)
                  for key in COUNTERS}
        for key in ("capture_failures", "decode_failures", "reconnects", "timestamp_discontinuities"):
            if deltas[key] > 0:
                failures.append(key)
        detect_fps = deltas["detected"] / elapsed_s
        if deltas["captured"] <= 0 or detect_fps < min_detect_fps:
            failures.append("camera_not_progressing")
        sequences = [row.get("telemetry", {}).get("sequence", 0) for row in rows]
        if max(sequences) <= min(sequences):
            failures.append("output_not_progressing")
        if any(after < before for before, after in zip(sequences, sequences[1:])):
            failures.append("output_sequence_reset")
        preview = previews.get(camera_id, {})
        if not preview.get("decoded"):
            failures.append("invalid_preview_jpeg")
        for key in ("overwritten_before_processing", "result_queue_drops", "driver_sequence_gaps"):
            if deltas[key] > 0:
                warnings.append(key)
        errors = [row["telemetry"]["pose"]["error_px"] for row in rows
                  if row.get("telemetry", {}).get("pose") and not telemetry_failures(row, expected_ids)]
        results[camera_id] = {
            "passed": not failures, "failures": failures, "warnings": warnings,
            "valid_sample_fraction": valid_fraction, "samples": len(rows),
            "sample_failures": {reason: sum(reason in problem for problem in problems)
                                for reason in sorted({reason for problem in problems for reason in problem})},
            "observed_tag_ids": sorted({tag["id"] for row in rows
                                         for tag in row.get("telemetry", {}).get("tags", [])}),
            "capture_fps": deltas["captured"] / elapsed_s, "detect_fps": detect_fps,
            "counter_deltas": deltas, "preview": preview,
            "max_reprojection_error_px": max(errors, default=None),
        }
    return {"passed": all(result["passed"] for result in results.values()),
            "elapsed_s": elapsed_s, "cameras": results}


def verify(base_url, *, duration_s=30., interval_s=1., expected_cameras=(), expected_ids=(),
           output_dir=None):
    if duration_s < interval_s or interval_s <= 0:
        raise ValueError("duration must be at least one positive sampling interval")
    base_url = base_url.rstrip("/")

    def get(path):
        with urlopen(base_url + path, timeout=10) as response:
            return response.read()

    health = json.loads(get("/healthz"))
    session_before = json.loads(get("/api/session/status"))
    samples = [json.loads(get("/api/dashboard"))]
    started = time.monotonic()
    while True:
        remaining = duration_s - (time.monotonic() - started)
        if remaining <= 0:
            break
        time.sleep(min(interval_s, remaining))
        samples.append(json.loads(get("/api/dashboard")))
    elapsed = time.monotonic() - started
    previews = {}
    import cv2
    import numpy as np

    ids = set(expected_cameras) or {camera["id"] for camera in samples[0]["cameras"] if camera["enabled"]}
    destination = Path(output_dir) if output_dir else None
    if destination:
        destination.mkdir(parents=True, exist_ok=True)
    for camera_id in sorted(ids):
        jpeg = get(f"/api/camera/{quote(camera_id, safe='')}/frame.jpg")
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
        previews[camera_id] = {"decoded": decoded is not None, "bytes": len(jpeg),
                               "size": None if decoded is None else list(decoded.shape[::-1])}
        if destination:
            # IDs are URL-encoded for filesystem safety, too.
            (destination / f"camera-{quote(camera_id, safe='')}.jpg").write_bytes(jpeg)
    report = evaluate_samples(samples, elapsed, previews, expected_cameras=expected_cameras,
                              expected_ids=expected_ids)
    report.update({"checked_at": datetime.now(timezone.utc).isoformat(), "base_url": base_url,
                   "ready": bool(health.get("ready")), "session_id": session_before.get("session_id"),
                   "gates": {"min_valid_fraction": .9, "min_detect_fps": 1.}})
    if not health.get("ready"):
        report["passed"] = False
        report["global_failures"] = ["daemon_not_ready"]
    if destination:
        (destination / "samples.json").write_text(json.dumps(samples, indent=2, allow_nan=False) + "\n")
        (destination / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://192.168.69.170:8765")
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--camera", action="append", default=[])
    parser.add_argument("--expected-tag", type=int, action="append", default=[])
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    try:
        report = verify(args.url, duration_s=args.duration, interval_s=args.interval,
                        expected_cameras=args.camera, expected_ids=args.expected_tag,
                        output_dir=args.output_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        return 2
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
