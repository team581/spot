"""Fixed-image regression through the production capture/detect/pose/transport path."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from .config import ConfigError, load_calibration, load_config
from .models import DetectedFrame, FramePacket
from .native import create_detector
from .pose import FieldLayout, PoseSolver, robot_from_camera_transform, select_robot_pose
from .transport import make_vision_frame


def run_image_regression(
    manifest_path: str | Path, *, backend: str = "cpu", repeats: int = 5
) -> dict:
    # Import lazily to keep the CLI's recording conversion as the one pixel boundary.
    from .cli import _recording_frames

    if repeats < 1:
        raise ValueError("repeats must be positive")
    if backend not in {"cpu", "cuda"}:
        raise ValueError("backend must be cpu or cuda")
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text())
    base = path.parent
    config = load_config(base / manifest["config"])
    if config.field_layout is None:
        raise ConfigError("Image regression requires a field layout")
    layout = FieldLayout.load(config.field_layout, config.field_revision)
    results = []
    for case in manifest["cases"]:
        case_config = load_config(base / case["config"]) if case.get("config") else config
        camera = case_config.camera(manifest["camera"])
        # The imported GPU supports only 2x decimation. Record this explicitly
        # rather than sending a CPU corpus setting into its fatal native CHECK.
        decimate = 2.0 if backend == "cuda" else camera.detector.decimate
        camera = replace(
            camera,
            detector=replace(
                camera.detector, backend=backend, decimate=decimate, fallback_to_cpu=False
            ),
        )
        if camera.calibration is None:
            raise ConfigError("Image regression requires camera calibration")
        calibration = load_calibration(camera.calibration)
        calibration.validate_for(camera)
        calibration = calibration.for_image_rotation(camera)
        detector = create_detector(camera, calibration)
        solver = PoseSolver(calibration, layout, config.tag_size_m)
        image = next(_recording_frames(base / case["image"], camera))
        detector.detect(image)  # Warm-up excluded from comparable timing samples.
        timings = []
        for _ in range(repeats):
            started = time.perf_counter_ns()
            batch = detector.detect(image)
            solution = solver.solve(batch.detections)
            pose = select_robot_pose(
                solution,
                robot_from_camera_transform(
                    camera.robot_from_camera_translation, camera.robot_from_camera_rpy_deg
                ),
            )
            frame = FramePacket(camera.id, 1, 1, 1000, time.monotonic_ns(), image)
            message = make_vision_frame(
                config,
                camera,
                DetectedFrame(frame, batch, 0),
                solution,
                (time.perf_counter_ns() - started) / 1e6,
            )
            from .protocol import restore, snapshot

            wire = restore(type(message), snapshot(message))
            timings.append(
                [(time.perf_counter_ns() - started) / 1e6, batch.detect_ms, solution.solve_ms]
            )
        expected = {tag["id"]: tag for tag in case["tags"]}
        found = {d.id: d for d in batch.detections}
        failures = []
        if sorted(d.id for d in batch.detections) != sorted(expected):
            failures.append("tag_ids")
        errors = [
            float(
                np.linalg.norm(
                    found[tag_id].corners - np.asarray(expected[tag_id]["corners"]), axis=1
                ).max()
            )
            for tag_id in expected.keys() & found.keys()
        ]
        corner_error = max(errors, default=None)
        if corner_error is not None and (
            not np.isfinite(corner_error) or corner_error > case["max_corner_error_px"]
        ):
            failures.append("corner_error")
        translation_error = None
        reprojection_error = None
        rotation_error = None
        if expected:
            if pose is None:
                failures.append("missing_pose")
            else:
                translation_error = float(
                    np.linalg.norm(pose.translation - case["robot_translation_m"])
                )
                reprojection_error = pose.reprojection_error_px
                quaternion = np.asarray(case["robot_quaternion_wxyz"], dtype=np.float64)
                cosine = abs(
                    float(np.dot(pose.quaternion_wxyz, quaternion / np.linalg.norm(quaternion)))
                )
                rotation_error = float(np.rad2deg(2 * np.arccos(np.clip(cosine, 0.0, 1.0))))
                if not all(
                    np.isfinite(value)
                    for value in (translation_error, reprojection_error, rotation_error)
                ):
                    failures.append("nonfinite_accuracy")
                if rotation_error > case["max_rotation_error_deg"]:
                    failures.append("rotation_error")
                if translation_error > case["max_translation_error_m"]:
                    failures.append("translation_error")
                if reprojection_error > case["max_reprojection_error_px"]:
                    failures.append("reprojection_error")
            if len(wire.candidates) != len(solution.candidates) or not solution.used_tag_ids:
                failures.append("pose_transport")
        elif wire.candidates or pose is not None:
            failures.append("unexpected_pose")
        timing = np.asarray(timings)
        results.append(
            {
                "name": case["name"],
                "passed": not failures,
                "failures": failures,
                "detector_decimate": decimate,
                "expected_ids": sorted(expected),
                "detected_ids": sorted(found),
                "max_corner_error_px": corner_error,
                "translation_error_m": translation_error,
                "reprojection_error_px": reprojection_error,
                "rotation_error_deg": rotation_error,
                "distortion_factors_px": {d.id: d.distortion_factor_px for d in batch.detections},
                "timing_ms": {
                    "pipeline_mean": float(timing[:, 0].mean()),
                    "pipeline_p95": float(np.percentile(timing[:, 0], 95)),
                    "detect_mean": float(timing[:, 1].mean()),
                    "solve_mean": float(timing[:, 2].mean()),
                },
            }
        )
    if not results:
        raise ValueError("manifest must contain at least one case")
    return {
        "backend": backend,
        "repeats": repeats,
        "passed": all(result["passed"] for result in results),
        "cases": results,
    }
