"""CUDA detector and optional host geometry diagnostics."""

from collections.abc import Sequence

import numpy as np

CUDA_AVAILABLE: bool

class CameraMatrix:
    fx: float
    fy: float
    cx: float
    cy: float
    def __init__(self) -> None: ...

class DistortionCoefficients:
    k1: float
    k2: float
    p1: float
    p2: float
    k3: float
    def __init__(self) -> None: ...

class DetectorOptions:
    family: str
    decimate: float
    blur: float
    threads: int
    refine_edges: bool
    max_hamming: int
    def __init__(self) -> None: ...

class Detection:
    id: int
    hamming: int
    decision_margin: float
    corners: list[list[float]]

class DetectionBatch:
    detections: list[Detection]
    detect_ms: float
    input_address: int

class DetectorMetrics:
    calls: int
    last_detect_ms: float
    total_detect_ms: float
    last_input_address: int

class CudaDetector:
    def __init__(
        self,
        width: int,
        height: int,
        camera: CameraMatrix,
        distortion: DistortionCoefficients,
        options: DetectorOptions,
    ) -> None: ...
    def detect(self, frame: np.ndarray) -> DetectionBatch: ...
    def metrics(self) -> DetectorMetrics: ...
    def reset(self) -> None: ...

def undistort_points(
    points: Sequence[Sequence[float]], camera: CameraMatrix, distortion: DistortionCoefficients
) -> list[list[float]]: ...
def refine_corners(
    frame: np.ndarray,
    corners: Sequence[Sequence[float]],
    camera: CameraMatrix,
    distortion: DistortionCoefficients,
    decimate: float = 2.0,
) -> list[list[float]]: ...
