"""Intermediate models for profile snapshots and NetworkTables struct construction."""

from dataclasses import dataclass
from dataclasses import field as data_field

from .config import DetectorConfig


@dataclass
class Pose:
    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    qw: float = 0.0
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0


@dataclass
class OpticalMode:
    id: str = ""
    width: int = 0
    height: int = 0
    pixel_format: str = ""
    fps: int = 0
    optical_signature: str = ""


@dataclass
class ControlPolicy:
    name: str = ""
    default_value: float = 0.0
    allow_override: bool = False
    required: bool = False


@dataclass
class CameraDefinition:
    name: str = ""
    required: bool = False
    enabled: bool = False
    robot_to_camera: Pose = data_field(default_factory=Pose)
    image_rotation_deg: int = 0
    allowed_modes: list[OpticalMode] = data_field(default_factory=list)
    controls: list[ControlPolicy] = data_field(default_factory=list)
    binding_id: str = ""
    calibration: dict | None = None
    timestamp_qualification: dict | None = None
    detector: DetectorConfig = data_field(default_factory=DetectorConfig)


@dataclass
class FieldTag:
    id: int = 0
    field_to_tag: Pose = data_field(default_factory=Pose)
    size_m: float = 0.0


@dataclass
class FieldLayout:
    origin: str = ""
    length_m: float = 0.0
    width_m: float = 0.0
    tags: list[FieldTag] = data_field(default_factory=list)


@dataclass
class Profile:
    cameras: list[CameraDefinition] = data_field(default_factory=list)
    field: FieldLayout = data_field(default_factory=FieldLayout)
    fusion_enabled: bool = False
    heading_enabled: bool = False
    max_age_s: float = 0.0
    future_tolerance_s: float = 0.0
    reorder_window_s: float = 0.0
    processing: dict = data_field(default_factory=dict)


@dataclass
class RobotConfiguration:
    cameras: list[CameraDefinition] = data_field(default_factory=list)
    processing: dict = data_field(default_factory=dict)


@dataclass
class Manifest:
    profile: Profile = data_field(default_factory=Profile)


@dataclass
class RobotState:
    tag_selection_generation: int = 0
    allowed_tag_ids: list[int] = data_field(default_factory=list)


@dataclass
class PoseCandidate:
    field_to_camera: Pose = data_field(default_factory=Pose)
    method: int = 0
    tag_ids: list[int] = data_field(default_factory=list)
    reprojection_error_px: float = 0.0
    average_tag_distance_m: float = 0.0
    image_area_fraction: float = 0.0
    image_spread_fraction: float = 0.0
    distortion_displacement_px: float = 0.0


@dataclass
class TagObservation:
    id: int = 0
    corners_xy_px: list[float] = data_field(default_factory=list)


@dataclass
class ProcessingTiming:
    capture_to_detect_ms: float = 0.0
    detect_ms: float = 0.0
    solve_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class Observation:
    capture_epoch: str = ""
    sequence: int = 0
    camera_name: str = ""
    runtime_generation: str = ""
    robot_to_camera: Pose = data_field(default_factory=Pose)
    calibration_valid: bool = False
    capture_local_nt_us: int = 0
    timestamp_source: str = ""
    timestamp_uncertainty_s: float = 0.0
    candidates: list[PoseCandidate] = data_field(default_factory=list)
    tags: list[TagObservation] = data_field(default_factory=list)
    timing: ProcessingTiming = data_field(default_factory=ProcessingTiming)
    tag_selection_generation: int = 0
