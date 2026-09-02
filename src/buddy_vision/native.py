from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .config import Calibration, CameraConfig
from .models import Detection, DetectionBatch

LOGGER = logging.getLogger(__name__)


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> DetectionBatch: ...
    def reset(self) -> None: ...


@dataclass
class NativeDetector:
    implementation: object

    def detect(self, frame: np.ndarray) -> DetectionBatch:
        native = self.implementation.detect(frame)
        detections = tuple(Detection(
            id=int(item.id),
            corners=np.asarray(item.corners, dtype=np.float64).reshape(4, 2),
            hamming=int(item.hamming),
            decision_margin=float(item.decision_margin),
        ) for item in native.detections)
        return DetectionBatch(detections, float(native.detect_ms), int(native.input_address))

    def reset(self) -> None:
        self.implementation.reset()


@dataclass
class FallbackDetector:
    primary: Detector
    fallback: Detector
    using_fallback: bool = False

    def detect(self, frame: np.ndarray) -> DetectionBatch:
        if self.using_fallback:
            return self.fallback.detect(frame)
        try:
            return self.primary.detect(frame)
        except Exception:
            LOGGER.exception("CUDA detector failed; switching permanently to CPU fallback")
            self.using_fallback = True
            return self.fallback.detect(frame)

    def reset(self) -> None:
        self.primary.reset()
        self.fallback.reset()
        self.using_fallback = False


def create_detector(camera: CameraConfig, calibration: Calibration | None) -> Detector:
    try:
        from . import _buddy_cuda as native
    except ImportError as exc:
        raise RuntimeError("_buddy_cuda is not installed; build this package on the Jetson") from exc
    if not getattr(native, "CUDA_AVAILABLE", False):
        raise RuntimeError("this package was built without CUDA detector support")

    options = native.DetectorOptions()
    options.family = camera.detector.family
    options.decimate = camera.detector.decimate
    options.blur = camera.detector.blur
    options.threads = camera.detector.threads
    options.refine_edges = camera.detector.refine_edges
    options.max_hamming = camera.detector.max_hamming
    if camera.detector.backend == "cpu":
        return NativeDetector(native.CpuDetector(camera.width, camera.height, options))

    matrix = native.CameraMatrix()
    distortion = native.DistortionCoefficients()
    matrix.fx = float(max(camera.width, camera.height))
    matrix.fy = float(max(camera.width, camera.height))
    matrix.cx = camera.width / 2.0
    matrix.cy = camera.height / 2.0
    if calibration is not None:
        matrix.fx = calibration.camera_matrix[0][0]
        matrix.fy = calibration.camera_matrix[1][1]
        matrix.cx = calibration.camera_matrix[0][2]
        matrix.cy = calibration.camera_matrix[1][2]
        values = calibration.distortion + (0.0,) * (5 - len(calibration.distortion))
        distortion.k1, distortion.k2, distortion.p1, distortion.p2, distortion.k3 = values[:5]
    fallback = (NativeDetector(native.CpuDetector(camera.width, camera.height, options))
                if camera.detector.fallback_to_cpu else None)
    try:
        primary = NativeDetector(native.CudaDetector(
            camera.width, camera.height, matrix, distortion, options))
    except Exception:
        if fallback is None:
            raise
        LOGGER.exception("CUDA detector initialization failed; using CPU fallback")
        return fallback
    return primary if fallback is None else FallbackDetector(primary, fallback)
