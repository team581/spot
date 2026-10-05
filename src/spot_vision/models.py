from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any

import numpy as np


class CameraState(str, Enum):
    DISABLED = "DISABLED"
    DISCOVERING = "DISCOVERING"
    CONFIGURING = "CONFIGURING"
    RUNNING = "RUNNING"
    NO_TARGETS = "NO_TARGETS"
    RETRY_WAIT = "RETRY_WAIT"
    CONFIG_MISMATCH = "CONFIG_MISMATCH"


class PoseMethod(IntEnum):
    METHOD_UNKNOWN = 0
    MULTI_TAG_SQPNP = 1
    SINGLE_TAG_IPPE_SQUARE = 2


@dataclass(frozen=True)
class Detection:
    id: int
    corners: np.ndarray
    hamming: int = 0
    decision_margin: float = 0.0
    distortion_factor_px: float | None = None


@dataclass(frozen=True)
class DetectionBatch:
    detections: tuple[Detection, ...]
    detect_ms: float
    input_address: int = 0


@dataclass(frozen=True)
class FramePacket:
    camera_id: str
    sequence: int
    camera_frame_sequence: int
    capture_timestamp_us: int
    captured_monotonic_ns: int
    image: np.ndarray


@dataclass(frozen=True)
class DetectedFrame:
    frame: FramePacket
    batch: DetectionBatch
    capture_to_detect_ms: float


@dataclass(frozen=True)
class PoseCandidate:
    method: PoseMethod
    translation: np.ndarray
    quaternion_wxyz: np.ndarray
    reprojection_error_px: float
    tag_ids: tuple[int, ...]
    average_tag_distance_m: float = 0.0
    distortion_factor_px: float = 0.0


@dataclass(frozen=True)
class PoseSolution:
    candidates: tuple[PoseCandidate, ...] = ()
    used_tag_ids: frozenset[int] = frozenset()
    rejection_reasons: dict[int, str] = field(default_factory=dict)
    solve_ms: float = 0.0


@dataclass
class CameraCounters:
    captured: int = 0
    detected: int = 0
    capture_failures: int = 0
    decode_failures: int = 0
    overwritten_before_processing: int = 0
    driver_sequence_gaps: int = 0
    result_queue_drops: int = 0
    timestamp_discontinuities: int = 0
    reconnects: int = 0
    state: CameraState = CameraState.DISCOVERING
    error: str = ""
    configuration_error: str = ""
    fps_capture: float = 0.0
    fps_detect: float = 0.0
    last_capture_monotonic: float = 0.0
    last_detection_monotonic: float = 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "captured": self.captured,
            "detected": self.detected,
            "capture_failures": self.capture_failures,
            "decode_failures": self.decode_failures,
            "overwritten_before_processing": self.overwritten_before_processing,
            "driver_sequence_gaps": self.driver_sequence_gaps,
            "result_queue_drops": self.result_queue_drops,
            "timestamp_discontinuities": self.timestamp_discontinuities,
            "reconnects": self.reconnects,
            "state": self.state.value,
            "error": self.error,
            "configuration_error": self.configuration_error,
            "fps_capture": self.fps_capture,
            "fps_detect": self.fps_detect,
        }
