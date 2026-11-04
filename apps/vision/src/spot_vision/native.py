from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np

from .config import Calibration, CameraConfig
from .models import Detection, DetectionBatch
from .uncertainty import distortion_factors

if TYPE_CHECKING:
    from ._spot_cuda import CpuDetector, CudaDetector

LOGGER = logging.getLogger(__name__)


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> DetectionBatch: ...
    def reset(self) -> None: ...


@dataclass
class NativeDetector:
    implementation: CpuDetector | CudaDetector
    calibration: Calibration | None = None

    def detect(self, frame: np.ndarray) -> DetectionBatch:
        native = self.implementation.detect(frame)
        factors = (
            None
            if self.calibration is None
            else distortion_factors(
                np.asarray([item.corners for item in native.detections]), self.calibration
            )
        )
        detections = tuple(
            Detection(
                id=int(item.id),
                corners=np.asarray(item.corners, dtype=np.float64).reshape(4, 2),
                hamming=int(item.hamming),
                decision_margin=float(item.decision_margin),
                distortion_factor_px=None if factors is None else float(factors[index]),
            )
            for index, item in enumerate(native.detections)
        )
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
    if camera.detector.backend == "cuda" and (camera.width % 8 or camera.height % 8):
        raise RuntimeError("CUDA detector dimensions must be multiples of 8")
    try:
        from . import _spot_cuda as native
    except ImportError as exc:
        raise RuntimeError(
            "_spot_cuda is not installed; build this package with the CPU or CUDA detector"
        ) from exc
    if camera.detector.backend == "cuda" and not getattr(native, "CUDA_AVAILABLE", False):
        raise RuntimeError("this package was built without CUDA detector support")

    options = native.DetectorOptions()
    options.family = camera.detector.family
    options.decimate = camera.detector.decimate
    options.blur = camera.detector.blur
    options.threads = camera.detector.threads
    options.refine_edges = camera.detector.refine_edges
    options.max_hamming = camera.detector.max_hamming
    if camera.detector.backend == "cpu":
        return NativeDetector(native.CpuDetector(camera.width, camera.height, options), calibration)

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
    fallback = (
        NativeDetector(native.CpuDetector(camera.width, camera.height, options), calibration)
        if camera.detector.fallback_to_cpu
        else None
    )
    try:
        # The imported CUDA refinement supports five coefficients. Never silently
        # truncate rational/thin-prism/tilted-sensor models to a different lens.
        if calibration is not None and any(calibration.distortion[5:]):
            raise RuntimeError("CUDA edge refinement supports only the five-coefficient lens model")
        # The upstream constructor uses a fatal CHECK for this constraint.
        # Reject it here so the configured CPU fallback can still recover.
        if camera.detector.decimate != 2.0:
            raise RuntimeError("CUDA detector requires decimate=2")
        primary = NativeDetector(
            native.CudaDetector(camera.width, camera.height, matrix, distortion, options),
            calibration,
        )
    except Exception:
        if fallback is None:
            raise
        LOGGER.exception("CUDA detector initialization failed; using CPU fallback")
        return fallback
    return primary if fallback is None else FallbackDetector(primary, fallback)
