#!/usr/bin/env python3
"""Local bench run ledger, collection, reports and comparisons; no autonomous tuning.

Export WPILOG with basic-robot-tester's exportBenchLog task before reporting.
All reports are experimental evidence, never hardware qualification certificates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def stats(values):
    values = sorted(v for v in values if numeric(v) and v >= 0)
    if not values:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "p999": None, "max": None}
    result = {"n": len(values)}
    for key, p in (("p50", .5), ("p95", .95), ("p99", .99), ("p999", .999), ("max", 1)):
        result[key] = values[math.ceil(len(values) * p) - 1]
    result["max_over_p50"] = result["max"] / result["p50"] if result["p50"] else None
    result["over_100"] = sum(v > 100 for v in values)
    result["over_250"] = sum(v > 250 for v in values)
    return result


def analyze(path, manifest, warmup_s=0, duration_s=None):
    rows, telemetry, bad = [], [], 0
    for line in Path(path).read_text().splitlines():
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            bad += 1
            continue
        if not isinstance(row, dict):
            bad += 1
            continue
        if row.get("_kind") == "telemetry":
            if numeric(row.get("_log_fpga_s")):
                telemetry.append(row)
            else:
                bad += 1
            continue
        key = "consume_fpga_s" if row.get("decision") == "BENCH_FUSED" else "decision_fpga_s"
        if (not numeric(row.get(key)) or not numeric(row.get("capture_fpga_s"))
                or not isinstance(row.get("camera"), str) or not isinstance(row.get("decision"), str)):
            bad += 1
            continue
        row["_time"] = row[key]
        rows.append(row)
    times = [r["_time"] for r in rows] + [r["_log_fpga_s"] for r in telemetry]
    first, last = (min(times), max(times)) if times else (0, 0)
    start = first + warmup_s
    end = max(start, min(last, start + duration_s) if duration_s else last)
    span = max(0, end - start)
    selected = [r for r in rows if start <= r["_time"] <= end]
    checks = []
    if bad:
        checks.append(f"{bad} malformed exported records")
    if span <= 0:
        checks.append("No positive measurement interval")
    if duration_s and span < duration_s * .95:
        checks.append("Log covers less than 95% of requested measurement duration")
    cameras = {}
    for camera in manifest["cameras"]:
        decisions = sorted((r for r in selected if r["camera"] == camera and r["decision"] != "BENCH_FUSED"),
                           key=lambda r: r["_time"])
        consumed = sorted((r for r in selected if r["camera"] == camera and r["decision"] == "BENCH_FUSED"),
                          key=lambda r: r["_time"])
        ages = [(r["_time"] - r["capture_fpga_s"]) * 1000 for r in decisions]
        used_ages = [(r["_time"] - r["capture_fpga_s"]) * 1000 for r in consumed]
        accepted = [r for r in decisions if r["decision"] == "ACCEPTED"]
        arrivals = [start] + [r["_time"] for r in decisions] + [end]
        accepted_times = [start] + [r["_time"] for r in accepted] + [end]
        gaps = [(b - a) * 1000 for a, b in zip(arrivals, arrivals[1:])]
        accepted_gaps = [(b - a) * 1000 for a, b in zip(accepted_times, accepted_times[1:])]
        invalid = sum(not numeric(v) or v < 0 for v in ages + used_ages)
        # Frames absent before/after the observed stream count as gaps in the measurement window.
        item = {"delivered": len(decisions), "consumed": len(consumed), "accepted": len(accepted),
                "decision_fps": len(decisions) / span if span else 0,
                "accepted_fps": len(accepted) / span if span else 0,
                "decisions": dict(Counter(r["decision"] for r in decisions)),
                "decision_age_ms": stats(ages), "consumption_age_ms": stats(used_ages),
                "delivery_gap_ms": stats(gaps), "accepted_gap_ms": stats(accepted_gaps),
                "invalid_age_count": invalid,
                "negative_ages_ms": [v for v in ages + used_ages if v < 0][:10],
                "processing_ms": stats([r.get("processing_ms") for r in decisions])}
        cameras[camera] = item
        if not decisions:
            checks.append(f"{camera}: no delivered frames")
        if invalid:
            checks.append(f"{camera}: invalid or apparent-future ages require clock investigation")
        if item["decision_fps"] < manifest.get("min_decision_fps", 1):
            checks.append(f"{camera}: delivered rate below target")
        if ages and item["decision_age_ms"]["p95"] is not None and item["decision_age_ms"]["p95"] > 100:
            checks.append(f"{camera}: decision age p95 exceeds 100 ms")
        if manifest.get("scenario", "static") == "static" and item["delivery_gap_ms"]["max"] > 500:
            checks.append(f"{camera}: delivery gap exceeds 500 ms")
        if manifest.get("require_acceptance") and not accepted:
            checks.append(f"{camera}: no accepted poses")
        if manifest.get("require_acceptance") and item["accepted_gap_ms"]["max"] > 500:
            checks.append(f"{camera}: accepted-pose gap exceeds 500 ms")
        if manifest.get("require_consumption") and not consumed:
            checks.append(f"{camera}: no estimator consumptions")
        if consumed and item["consumption_age_ms"]["p95"] is not None and item["consumption_age_ms"]["p95"] > 100:
            checks.append(f"{camera}: consumption age p95 exceeds 100 ms")
    samples = [r for r in telemetry if start <= r["_log_fpga_s"] <= end]
    metrics = {}
    for key in ("Bench/LoopIntervalMs", "Bench/LoopWorkMs", "Bench/LoggingErrors", "Bench/MalformedPackets",
                "Bench/SyncUpdateAgeS", "Vision/Spot/QueueDrops"):
        metrics[key] = stats([r.get("value") for r in samples if r.get("key") == key])
    for key in ("Bench/LoggingErrors", "Bench/MalformedPackets", "Vision/Spot/QueueDrops"):
        if metrics[key]["max"] is not None and metrics[key]["max"] > 0:
            checks.append(f"{key}: nonzero cumulative counter (inspect reset/window boundaries)")
    return {"schema_version": 1, "hardware_qualified": False, "manifest": manifest,
            "window": {"start_fpga_s": start, "end_fpga_s": end, "duration_s": span,
                       "warmup_s": warmup_s, "requested_duration_s": duration_s},
            "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "malformed_rows": bad, "cameras": cameras, "telemetry": metrics,
            "review_required": checks, "screening_passed": not checks,
            "limits": ["A measured trace is not a worst-case timing guarantee.",
                       "Read-completion timestamps omit unqualified exposure/USB/decode bias.",
                       "Withheld upstream frames are absent; correlate Jetson counters.",
                       "No hardware qualification or independent clock verification is inferred."]}


def compare(baseline, candidate):
    reasons = []
    for key in ("cameras", "scenario", "require_acceptance", "require_consumption"):
        if baseline["manifest"].get(key) != candidate["manifest"].get(key):
            reasons.append(f"Nonmatching {key}")
    if not baseline["screening_passed"] or not candidate["screening_passed"]:
        reasons.append("At least one run failed screening; investigate before selecting a winner")
    before_duration = baseline["window"]["duration_s"]
    after_duration = candidate["window"]["duration_s"]
    if not before_duration or not .8 <= after_duration / before_duration <= 1.25:
        reasons.append("Measurement durations differ by more than 25%")
    if reasons:
        return {"recommendation": "inconclusive", "reasons": reasons}
    differences = {}
    for name in baseline["cameras"]:
        before, after = baseline["cameras"][name], candidate["cameras"][name]
        delta = after["decision_age_ms"]["p95"] - before["decision_age_ms"]["p95"]
        differences[name] = {"decision_p95_delta_ms": delta,
                             "decision_fps_ratio": after["decision_fps"] / before["decision_fps"]}
        if delta > 2 or differences[name]["decision_fps_ratio"] < .9:
            reasons.append(f"{name}: p95/rate regression; reject pending repeated evidence")
        if after["decision_age_ms"]["max"] > before["decision_age_ms"]["max"] + 20:
            reasons.append(f"{name}: observed maximum regressed by more than 20 ms")
        if baseline["manifest"].get("require_consumption"):
            if after["consumption_age_ms"]["p95"] > before["consumption_age_ms"]["p95"] + 2:
                reasons.append(f"{name}: estimator-consumption p95 regression")
    return {"recommendation": "reject_candidate" if reasons else "repeat_candidate",
            "reasons": reasons or ["Repeat across restarts and stress before adopting; compare quality separately"],
            "differences": differences}


def safe_name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ValueError("Use a bounded run name containing letters, digits, dash, underscore or dot")
    return value


def doctor(path):
    latest, latest_record, errors = None, None, 0
    for line in Path(path).read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            errors += 1
            continue
        if isinstance(row, dict) and isinstance(row.get("status"), dict):
            latest = row["status"]
            latest_record = row
        else:
            errors += 1
    if latest is None:
        return {"issues": ["No successful status snapshots: check HTTP port/service/local access"],
                "request_errors": errors}
    issues = []
    if not latest.get("connected"):
        issues.append("Robot link disconnected: check direct Ethernet addresses and explicit nt.server")
    if latest.get("lock_reason"):
        issues.append("Editing locked: " + str(latest["lock_reason"]))
    if latest.get("clock", {}).get("state") != "Synchronized":
        issues.append("NT clock is not synchronized")
    cameras = []
    for camera in latest.get("cameras", []):
        cameras.append({k: camera.get(k) for k in ("name", "logical_name", "connected", "health",
                                                   "fault", "calibrated", "timestamp_qualified",
                                                   "mode_id", "mode_signature", "metrics", "processing")})
        for key, message in (("connected", "Capture not verified: check USB binding/mode/controls"),
                             ("calibrated", "Intrinsic calibration required"),
                             ("timestamp_qualified", "Matching measured timing evidence required")):
            if camera.get(key) is False:
                issues.append(f"{camera.get('name')}: {message}")
        if camera.get("fault"):
            issues.append(f"{camera.get('name')}: {camera['fault']}")
        unsupported = [m.get("id") for m in camera.get("allowed_modes", []) if not m.get("supported")]
        if unsupported:
            issues.append(f"{camera.get('name')}: capture request is not advertised: {unsupported}")
    return {"robot_id": latest.get("robot_id"), "connected": latest.get("connected"),
            "clock": latest.get("clock"), "cameras": cameras, "faults": latest.get("faults", []),
            "snapshot_wall_time_s": latest_record.get("wall_time_s"),
            "snapshot_elapsed_s": latest_record.get("elapsed_s"),
            "fresh": latest.get("fresh"), "revision": latest.get("revision"),
            "applied_generation": latest.get("applied_generation"),
            "robot_decisions": latest.get("robot_decisions", {}),
            "issues": issues, "request_errors": errors,
            "note": "Latest available snapshot only; inspect timestamps before treating it as live."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new-run")
    new.add_argument("directory", type=Path)
    new.add_argument("--cameras", nargs="+", required=True)
    new.add_argument("--scenario", choices=["static", "rotation", "occlusion", "recovery"], default="static")
    new.add_argument("--hypothesis", required=True)
    new.add_argument("--require-acceptance", action="store_true")
    new.add_argument("--require-consumption", action="store_true")
    report = commands.add_parser("report")
    report.add_argument("directory", type=Path)
    report.add_argument("--frames", type=Path, required=True)
    report.add_argument("--warmup-s", type=float, default=0)
    report.add_argument("--duration-s", type=float)
    diagnostic = commands.add_parser("doctor")
    diagnostic.add_argument("status", type=Path)
    diff = commands.add_parser("compare")
    diff.add_argument("baseline", type=Path)
    diff.add_argument("candidate", type=Path)
    collect = commands.add_parser("collect")
    collect.add_argument("directory", type=Path)
    collect.add_argument("--host", required=True)
    collect.add_argument("--user", required=True)
    collect.add_argument("--remote", required=True)
    collect.add_argument("--identity", type=Path)
    args = parser.parse_args()
    if args.command == "new-run":
        for camera in args.cameras:
            safe_name(camera)
        if len(set(args.cameras)) != len(args.cameras):
            parser.error("Camera names must be unique")
        args.directory.mkdir(parents=True, exist_ok=False)
        snapshots = args.directory / "config"
        snapshots.mkdir()
        fingerprints = {}
        for relative in ["basic-robot-tester/src/main/java/frc/robot/vision/VisionConfig.java",
                         "basic-robot-tester/src/main/java/frc/robot/BenchConfig.java",
                         "config/beta-installation.json"]:
            path = ROOT / relative
            shutil.copy2(path, snapshots / path.name)
            fingerprints[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {"schema_version": 1, "cameras": args.cameras, "scenario": args.scenario,
                    "hypothesis": args.hypothesis, "require_acceptance": args.require_acceptance,
                    "require_consumption": args.require_consumption, "min_decision_fps": 1,
                    "source_hashes": fingerprints,
                    "notes": "Record actual installed profile/release hashes, modes, readback, tag geometry, run duration and power mode here. Snapshot installation JSON is a repo default, not live state."}
        write(args.directory / "manifest.json", manifest)
        (args.directory / "operator-notes.md").write_text(
            "# Agent robot integration run\n\n"
            + "Hypothesis: " + args.hypothesis + "\n\n"
            + "Actual topology / addresses / management path: \n"
            + "Installed release/config hash and applied robot profile hash: \n"
            + "Capture readback / tag geometry / prerequisites: \n"
            + "Start/end time and interruption times: \n"
            + "Agent commands / edits / restarts / time to first fresh decision: \n\n"
            + "| Step/action | Expected | Actual / evidence | Time / friction |\n"
            + "| --- | --- | --- | --- |\n"
            + "| First blocked checklist step | | | |\n\n"
            + "One proposed cause: \nExact retest and expected result: \n"
            + "Fresh-session repeat result: \nAgent checkpoint / exact next action: \n"
            + "Human physical assistance needed, if any: \n")
        print(args.directory / "manifest.json")
    elif args.command == "report":
        if args.warmup_s < 0 or not math.isfinite(args.warmup_s):
            parser.error("Warmup must be finite and nonnegative")
        if args.duration_s is not None and (not math.isfinite(args.duration_s) or args.duration_s <= 0):
            parser.error("Duration must be finite and positive")
        summary = analyze(args.frames, json.loads((args.directory / "manifest.json").read_text()),
                          args.warmup_s, args.duration_s)
        write(args.directory / "summary.json", summary)
        brief = [f"Screening passed: {summary['screening_passed']}",
                 f"Window: {summary['window']['duration_s']:.1f}s; hardware qualification: NOT established"]
        for camera, item in summary["cameras"].items():
            brief.append(f"{camera}: delivered={item['delivered']}, fps={item['decision_fps']:.2f}, "
                         f"age_ms={item['decision_age_ms']}, accepted={item['accepted']}, consumed={item['consumed']}")
        brief.extend(summary["review_required"])
        (args.directory / "agent-brief.txt").write_text("\n".join(brief) + "\n")
        print("\n".join(brief))
    elif args.command == "compare":
        result = compare(json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text()))
        print(json.dumps(result, indent=2, allow_nan=False))
    elif args.command == "doctor":
        print(json.dumps(doctor(args.status), indent=2, allow_nan=False))
    elif args.command == "collect":
        for value in (args.host, args.user):
            safe_name(value)
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", args.remote) or "/../" in args.remote:
            parser.error("Remote must be an explicit absolute path without spaces, globs or shell syntax")
        dest = args.directory / "raw" / args.host
        dest.mkdir(parents=True, exist_ok=True)
        command = ["scp", "-r", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
        if args.identity:
            command += ["-i", str(args.identity.expanduser())]
        command += [f"{args.user}@{args.host}:{args.remote}", str(dest)]
        subprocess.run(command, check=True)
        print(dest)


if __name__ == "__main__":
    main()
