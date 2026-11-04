"""Spot data models; transport uses typed NetworkTables topics."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VisionFrame:
    camera_id: str = ""
    sequence: int = 0
    camera_frame_sequence: int = 0
    config_revision: int = 0
    field_revision: int = 0
    candidates: list[PoseCandidate] = field(default_factory=list)
    tags: list[TagObservation] = field(default_factory=list)
    timing: ProcessingTiming = field(default_factory=lambda: ProcessingTiming())


@dataclass
class PoseCandidate:
    method: int = 0
    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    qw: float = 0.0
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0
    reprojection_error_px: float = 0.0
    tag_ids: list[int] = field(default_factory=list)
    average_tag_distance_m: float = 0.0
    distortion_factor_px: float = 0.0


@dataclass
class TagObservation:
    id: int = 0
    corners_xy_px: list[float] = field(default_factory=list)
    hamming: int = 0
    decision_margin: float = 0.0
    used_for_pose: bool = False
    rejection_reason: str = ""
    distortion_factor_px: float | None = None


@dataclass
class ProcessingTiming:
    capture_to_detect_ms: float = 0.0
    detect_ms: float = 0.0
    solve_ms: float = 0.0
    total_ms: float = 0.0
