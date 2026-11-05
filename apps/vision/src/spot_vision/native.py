from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, Protocol

import numpy as np
from napa_vision import NapaDetector

from .config import Calibration, CameraConfig, DetectorConfig
from .models import Detection, DetectionBatch
from .uncertainty import distortion_factors

if TYPE_CHECKING:
    from ._spot_cuda import CudaDetector


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> DetectionBatch: ...
    def reset(self) -> None: ...


class CpuDetector:
    def __init__(
        self,
        width: int,
        height: int,
        options: DetectorConfig,
        calibration: Calibration | None = None,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("dimensions must be positive")
        self.width, self.height = width, height
        self.calibration = calibration
        self._lock = Lock()
        self._gray = np.empty((height, width), dtype=np.uint8)
        self._detector = NapaDetector(
            family="tag36h11",
            min_tag_px=16,
            max_hamming=options.max_hamming,
            min_contrast=3,
        )

    def detect(self, frame: np.ndarray) -> DetectionBatch:
        if frame.dtype != np.uint8:
            raise TypeError("frame must have dtype uint8")
        if frame.shape != (self.height, self.width, 2):
            raise ValueError("frame must have shape (height, width, 2)")
        if not frame.flags.c_contiguous:
            raise ValueError("frame must be packed, C-contiguous YUYV")
        with self._lock:
            start = perf_counter()
            np.copyto(self._gray, frame[:, :, 0])
            results = self._detector.detect(self._gray)
            detect_ms = (perf_counter() - start) * 1000
            detections = tuple(
                Detection(
                    id=item.tag_id,
                    # Preserve upstream AprilTag's decoded order and pixel origin
                    # for the existing pose solver and CUDA detection contract.
                    corners=item.corners[[1, 0, 3, 2]] + 0.5,
                    hamming=item.hamming,
                    decision_margin=item.decision_margin,
                )
                for item in results
            )
        if self.calibration is not None:
            factors = distortion_factors(
                np.asarray([d.corners for d in detections]), self.calibration
            )
            detections = tuple(
                replace(d, distortion_factor_px=float(factor))
                for d, factor in zip(detections, factors, strict=True)
            )
        return DetectionBatch(detections, detect_ms, int(frame.ctypes.data))

    def reset(self) -> None:
        # NAPA returns independent detections for each frame; no state needs clearing.
        pass


@dataclass
class NativeDetector:
    implementation: CudaDetector
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


def create_detector(camera: CameraConfig, calibration: Calibration | None) -> Detector:
    if camera.detector.backend == "cpu":
        return CpuDetector(camera.width, camera.height, camera.detector, calibration)
    if camera.detector.backend == "cuda" and (camera.width % 8 or camera.height % 8):
        raise RuntimeError("CUDA detector dimensions must be multiples of 8")
    try:
        from . import _spot_cuda as native
    except ImportError as exc:
        raise RuntimeError(
            "_spot_cuda is not installed; build this package with SPOT_BUILD_CUDA=ON"
        ) from exc
    if camera.detector.backend == "cuda" and not getattr(native, "CUDA_AVAILABLE", False):
        raise RuntimeError("this package was built without CUDA detector support")

    options = native.DetectorOptions()
    options.max_hamming = camera.detector.max_hamming
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
    # The imported CUDA refinement supports five coefficients. Never silently
    # truncate a different lens model or select a different backend here.
    if calibration is not None and any(calibration.distortion[5:]):
        raise RuntimeError("CUDA edge refinement supports only the five-coefficient lens model")
    return NativeDetector(
        native.CudaDetector(camera.width, camera.height, matrix, distortion, options),
        calibration,
    )
