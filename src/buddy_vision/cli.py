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

from .capture import CaptureWorker, enumerate_camera, resolve_device
from .config import ConfigError, load_calibration, load_config
from .logging_utils import configure_logging
from .models import CameraCounters, DetectionBatch
from .native import create_detector
from .pose import FieldLayout, PoseSolver
from .queues import LatestFrameSlot
from .service import VisionService

LOGGER = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buddy-vision")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json-logs", action="store_true")
    subcommands = parser.add_subparsers(dest="command", required=True)

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

    calibration = subcommands.add_parser("validate-calibration")
    calibration.add_argument("--config", required=True)
    calibration.add_argument("--camera", required=True)
    return parser


def _calibration(camera):
    if camera.calibration is None:
        return None
    calibration = load_calibration(camera.calibration)
    calibration.validate_for(camera)
    return calibration


def _batch_json(sequence: int, batch: DetectionBatch, total_ms: float,
                capture_fps: float = 0.0, drops: int = 0) -> str:
    return json.dumps({
        "sequence": sequence,
        "tags": [{
            "id": detection.id,
            "corners": detection.corners.tolist(),
            "hamming": detection.hamming,
            "decision_margin": detection.decision_margin,
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


def _recording_frames(path: str | Path, width: int, height: int) -> Iterator[np.ndarray]:
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
            if bgr.shape[:2] != (height, width):
                raise RuntimeError(
                    f"recording is {bgr.shape[1]}x{bgr.shape[0]}, expected {width}x{height}")
            yield cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_YUY2)
    finally:
        if frames is None:
            capture.release()


def _run_replay(args) -> int:
    config = load_config(args.config)
    camera = config.camera(args.camera)
    detector = create_detector(camera, _calibration(camera))
    for sequence, frame in enumerate(
            _recording_frames(args.input, camera.width, camera.height), start=1):
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
    for frame in _recording_frames(args.input, camera.width, camera.height):
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
    for frame in _recording_frames(args.input, camera.width, camera.height):
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose, args.json_logs)
    try:
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
        if args.command == "validate-calibration":
            return _run_validate_calibration(args)
    except (ConfigError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2
    parser.error(f"unhandled command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
