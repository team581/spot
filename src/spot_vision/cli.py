from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np

from .capture import CaptureWorker, enumerate_camera, orient_yuyv_frame, resolve_device
from .config import ConfigError, load_calibration, load_config
from .logging_utils import configure_logging
from .models import CameraCounters, DetectionBatch
from .native import create_detector
from .pose import FieldLayout, PoseSolver
from .queues import LatestFrameSlot
from .service import VisionService

LOGGER = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spot-vision")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json-logs", action="store_true")
    subcommands = parser.add_subparsers(dest="command", required=True)

    beta = subcommands.add_parser("beta", help="run the installed robot-integrated beta and GUI")
    beta.add_argument("--installation", default="/etc/spot-vision/beta.json")
    beta.add_argument("--state-root", default="/var/lib/spot-vision")

    verify = subcommands.add_parser("verify-release", help="verify installed Python/native identity")
    verify.add_argument("--backend", choices=("cpu", "cuda"), default="cuda")

    daemon = subcommands.add_parser("daemon", help="run the complete vision service")
    daemon.add_argument("--config", required=True)

    probe = subcommands.add_parser("probe", help="run headless live tag detection")
    probe.add_argument("--config", required=True)
    probe.add_argument("--camera", required=True)
    probe.add_argument("--frames", type=int, default=0, help="stop after N frames; 0 runs forever")

    modes = subcommands.add_parser("camera-modes", help="enumerate V4L2 modes and controls")
    modes.add_argument("--config", required=True)
    modes.add_argument("--camera", required=True)

    replay = subcommands.add_parser("replay", help="detect tags in an image or video")
    replay.add_argument("--config", required=True)
    replay.add_argument("--camera", required=True)
    replay.add_argument("--input", required=True)
    replay.add_argument("--frames", type=int, default=0)

    compare = subcommands.add_parser("compare", help="compare CPU and CUDA on a recording")
    compare.add_argument("--config", required=True)
    compare.add_argument("--camera", required=True)
    compare.add_argument("--input", required=True)
    compare.add_argument("--frames", type=int, default=100)

    benchmark = subcommands.add_parser("benchmark", help="benchmark a detector on a recording")
    benchmark.add_argument("--config", required=True)
    benchmark.add_argument("--camera", required=True)
    benchmark.add_argument("--input", required=True)
    benchmark.add_argument("--frames", type=int, default=300)

    regression = subcommands.add_parser("image-regression", help="measure fixed-image pipeline accuracy")
    regression.add_argument("--manifest", required=True)
    regression.add_argument("--backend", choices=("cpu", "cuda"), default="cpu")
    regression.add_argument("--repeats", type=int, default=5)
    regression.add_argument("--output", help="write the JSON metric report")

    calibration = subcommands.add_parser("validate-calibration")
    calibration.add_argument("--config", required=True)
    calibration.add_argument("--camera", required=True)

    charuco = subcommands.add_parser("calibrate-charuco", help="calibrate one camera from ChArUco images")
    charuco.add_argument("--input-dir", required=True)
    charuco.add_argument("--output", help="calibration JSON; defaults to the camera config path")
    charuco.add_argument("--config", help="camera service JSON (use with --camera)")
    charuco.add_argument("--camera", help="camera ID from --config")
    charuco.add_argument("--camera-id")
    charuco.add_argument("--width", type=int, required=True)
    charuco.add_argument("--height", type=int, required=True)
    charuco.add_argument("--squares-x", type=int, default=7)
    charuco.add_argument("--squares-y", type=int, default=5)
    charuco.add_argument("--square-length-m", type=float, default=0.04)
    charuco.add_argument("--marker-length-m", type=float, default=0.03)
    charuco.add_argument("--dictionary", default="DICT_4X4_50")
    charuco.add_argument("--model", choices=("plumb_bob", "rational"), default="plumb_bob")
    charuco.add_argument("--min-frames", type=int, default=15)
    return parser


def _calibration(camera):
    if camera.calibration is None:
        return None
    calibration = load_calibration(camera.calibration)
    calibration.validate_for(camera)
    return calibration.for_image_rotation(camera)


def _batch_json(sequence: int, batch: DetectionBatch, total_ms: float,
                capture_fps: float = 0.0, drops: int = 0) -> str:
    return json.dumps({
        "sequence": sequence,
        "tags": [{
            "id": detection.id,
            "corners": detection.corners.tolist(),
            "hamming": detection.hamming,
            "decision_margin": detection.decision_margin,
            "distortion_factor_px": detection.distortion_factor_px,
        } for detection in batch.detections],
        "capture_fps": capture_fps,
        "detect_ms": batch.detect_ms,
        "total_ms": total_ms,
        "dropped_before_processing": drops,
    }, separators=(",", ":"))


def _run_probe(args) -> int:
    config = load_config(args.config)
    camera = config.camera(args.camera)
    if not camera.enabled:
        raise ConfigError(f"camera {camera.id!r} is disabled")
    device = resolve_device(camera.selector)
    print(enumerate_camera(device), flush=True)
    detector = create_detector(camera, _calibration(camera))
    stop = threading.Event()
    slot = LatestFrameSlot()
    counters = CameraCounters()
    worker = CaptureWorker(camera, slot, counters, stop)
    worker.start()
    processed = 0
    try:
        while args.frames == 0 or processed < args.frames:
            frame = slot.take()
            if frame is None:
                if not worker.is_alive():
                    raise RuntimeError(counters.error or "capture worker exited")
                time.sleep(0.005)
                continue
            started = time.perf_counter_ns()
            batch = detector.detect(frame.image)
            total_ms = (time.perf_counter_ns() - started) / 1e6
            print(_batch_json(frame.sequence, batch, total_ms, counters.fps_capture,
                              counters.overwritten_before_processing), flush=True)
            processed += 1
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        slot.close()
        worker.join(timeout=3.0)
    return 0


def _recording_frames(path: str | Path, camera) -> Iterator[np.ndarray]:
    import cv2

    source = Path(path)
    still = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if still is not None:
        frames = [still]
    else:
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise RuntimeError(f"cannot open recording {source}")
        frames = None
    try:
        if frames is not None:
            iterator = iter(frames)
        else:
            def video_iterator():
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        return
                    yield frame
            iterator = video_iterator()
        for bgr in iterator:
            if bgr.shape[:2] != (camera.height, camera.width):
                raise RuntimeError(
                    f"recording is {bgr.shape[1]}x{bgr.shape[0]}, expected {camera.width}x{camera.height}")
            yield orient_yuyv_frame(cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_YUY2), camera)
    finally:
        if frames is None:
            capture.release()


def _run_replay(args) -> int:
    config = load_config(args.config)
    camera = config.camera(args.camera)
    detector = create_detector(camera, _calibration(camera))
    for sequence, frame in enumerate(
            _recording_frames(args.input, camera), start=1):
        started = time.perf_counter_ns()
        batch = detector.detect(frame)
        print(_batch_json(sequence, batch, (time.perf_counter_ns() - started) / 1e6))
        if args.frames and sequence >= args.frames:
            break
    return 0


def _run_compare(args) -> int:
    config = load_config(args.config)
    camera = config.camera(args.camera)
    calibration = _calibration(camera)
    gpu = create_detector(replace(camera, detector=replace(
        camera.detector, backend="cuda", fallback_to_cpu=False)),
                          calibration)
    cpu = create_detector(replace(camera, detector=replace(camera.detector, backend="cpu")),
                          calibration)
    mismatches = 0
    processed = 0
    max_corner_delta = 0.0
    for frame in _recording_frames(args.input, camera):
        gpu_batch = gpu.detect(frame)
        cpu_batch = cpu.detect(frame)
        gpu_by_id = {item.id: item for item in gpu_batch.detections}
        cpu_by_id = {item.id: item for item in cpu_batch.detections}
        if gpu_by_id.keys() != cpu_by_id.keys():
            mismatches += 1
        for tag_id in gpu_by_id.keys() & cpu_by_id.keys():
            max_corner_delta = max(max_corner_delta, float(np.max(np.abs(
                gpu_by_id[tag_id].corners - cpu_by_id[tag_id].corners))))
        processed += 1
        if processed >= args.frames:
            break
    print(json.dumps({"frames": processed, "id_mismatches": mismatches,
                      "max_corner_delta_px": max_corner_delta}, indent=2))
    return 1 if mismatches else 0


def _run_benchmark(args) -> int:
    config = load_config(args.config)
    camera = config.camera(args.camera)
    detector = create_detector(camera, _calibration(camera))
    durations: list[float] = []
    detections = 0
    for frame in _recording_frames(args.input, camera):
        batch = detector.detect(frame)
        durations.append(batch.detect_ms)
        detections += len(batch.detections)
        if len(durations) >= args.frames:
            break
    if not durations:
        raise RuntimeError("recording contains no frames")
    values = np.asarray(durations)
    print(json.dumps({
        "backend": camera.detector.backend,
        "frames": len(durations),
        "detections": detections,
        "mean_detect_ms": float(values.mean()),
        "p50_detect_ms": float(np.percentile(values, 50)),
        "p95_detect_ms": float(np.percentile(values, 95)),
        "processed_fps": float(1000.0 / values.mean()),
    }, indent=2))
    return 0


def _run_validate_calibration(args) -> int:
    config = load_config(args.config)
    camera = config.camera(args.camera)
    if camera.calibration is None:
        raise ConfigError(f"camera {camera.id!r} has no calibration path")
    calibration = load_calibration(camera.calibration)
    calibration.validate_for(camera)
    calibration = calibration.for_image_rotation(camera)
    layout = None
    if config.field_layout:
        layout = FieldLayout.load(config.field_layout, config.field_revision)
    PoseSolver(calibration, layout, config.tag_size_m)
    print(json.dumps({
        "camera": camera.id,
        "calibration": str(camera.calibration),
        "resolution": [calibration.width, calibration.height],
        "pixel_format": calibration.pixel_format,
        "reprojection_error_px": calibration.reprojection_error_px,
        "field_revision": None if layout is None else layout.revision,
    }, indent=2))
    return 0


def _run_charuco(args) -> int:
    import cv2

    from .charuco import (
        CalibrationOptions,
        CharucoBoardConfig,
        calibrate,
        detect_frame,
        write_calibration,
    )
    if bool(args.config) != bool(args.camera):
        raise ConfigError("--config and --camera must be provided together")
    configured_camera = None
    if args.config:
        configured_camera = load_config(args.config).camera(args.camera)
        if args.output is None:
            if configured_camera.calibration is None:
                raise ConfigError(f"camera {args.camera!r} has no calibration path")
            args.output = str(configured_camera.calibration)
    if args.output is None:
        raise ConfigError("--output is required unless --config and --camera are used")
    board = CharucoBoardConfig(args.squares_x, args.squares_y, args.square_length_m,
                               args.marker_length_m, args.dictionary)
    options = CalibrationOptions(model=args.model, min_frames=args.min_frames)
    frames = []
    for path in sorted(Path(args.input_dir).glob("*")):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            continue
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None or image.shape != (args.height, args.width):
            continue
        frame = detect_frame(image, board, options)
        if frame is not None:
            frames.append(frame)
    result, report = calibrate(frames, board, options)
    print(json.dumps({"accepted": report.accepted, "reason": report.reason,
                      "frames_used": report.frames_used, "coverage": report.coverage,
                      "diversity": report.diversity,
                      "rms_reprojection_error_px": report.rms_reprojection_error_px,
                      "rejected_frames": report.rejected_frames}, indent=2))
    if result is None:
        return 2
    if args.camera_id:
        result["camera_id"] = args.camera_id or args.camera
    write_calibration(args.output, result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose, args.json_logs)
    try:
        if args.command == "beta":
            from .beta_app import run_beta
            return run_beta(args)
        if args.command == "verify-release":
            from .release import installed_identity
            print(json.dumps(installed_identity(backend=args.backend), indent=2))
            return 0
        if args.command == "daemon":
            service = VisionService(load_config(args.config))
            service.run_forever()
            return 0
        if args.command == "probe":
            return _run_probe(args)
        if args.command == "camera-modes":
            config = load_config(args.config)
            print(enumerate_camera(resolve_device(config.camera(args.camera).selector)))
            return 0
        if args.command == "replay":
            return _run_replay(args)
        if args.command == "compare":
            return _run_compare(args)
        if args.command == "benchmark":
            return _run_benchmark(args)
        if args.command == "image-regression":
            from .regression import run_image_regression
            if args.repeats < 1:
                raise ConfigError("--repeats must be positive")
            report = run_image_regression(args.manifest, backend=args.backend, repeats=args.repeats)
            serialized = json.dumps(report, indent=2, allow_nan=False)
            if args.output:
                Path(args.output).write_text(serialized + "\n")
            print(serialized)
            return 0 if report["passed"] else 1
        if args.command == "validate-calibration":
            return _run_validate_calibration(args)
        if args.command == "calibrate-charuco":
            return _run_charuco(args)
    except (ConfigError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2
    parser.error(f"unhandled command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
