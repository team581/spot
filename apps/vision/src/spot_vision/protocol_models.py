"""Intermediate models for profile snapshots and NetworkTables struct construction."""

from dataclasses import dataclass, field


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
    robot_to_camera: Pose = field(default_factory=Pose)
    image_rotation_deg: int = 0
    allowed_modes: list[OpticalMode] = field(default_factory=list)
    controls: list[ControlPolicy] = field(default_factory=list)


@dataclass
class FieldTag:
    id: int = 0
    field_to_tag: Pose = field(default_factory=Pose)
    size_m: float = 0.0


@dataclass
class FieldLayout:
    origin: str = ""
    length_m: float = 0.0
    width_m: float = 0.0
    tags: list[FieldTag] = field(default_factory=list)


@dataclass
class Profile:
    robot_id: str = ""
    cameras: list[CameraDefinition] = field(default_factory=list)
    field: FieldLayout = field(default_factory=FieldLayout)
    fusion_enabled: bool = False
    heading_enabled: bool = False
    max_age_s: float = 0.0
    future_tolerance_s: float = 0.0
    reorder_window_s: float = 0.0


@dataclass
class Manifest:
    profile: Profile = field(default_factory=Profile)
    robot_session: str = ""
    manifest_hash: str = ""


@dataclass
class RobotState:
    robot_session: str = ""
    enabled: bool = False
    sequence: int = 0
    tag_selection_generation: int = 0
    allowed_tag_ids: list[int] = field(default_factory=list)


@dataclass
class CameraGeneration:
    camera_name: str = ""
    binding_id: str = ""
    binding_generation: int = 0
    calibration_hash: str = ""
    mode_id: str = ""
    optical_signature: str = ""
    calibration_valid: bool = False


@dataclass
class Acknowledgement:
    robot_id: str = ""
    robot_session: str = ""
    manifest_hash: str = ""
    service_session: str = ""
    connection_epoch: int = 0
    sync_epoch: int = 0
    runtime_generation: str = ""
    field_hash: str = ""
    cameras: list[CameraGeneration] = field(default_factory=list)
    applied: bool = False
    error: str = ""
    tag_selection_supported: bool = False


@dataclass
class PoseCandidate:
    field_to_camera: Pose = field(default_factory=Pose)
    method: int = 0
    tag_ids: list[int] = field(default_factory=list)
    reprojection_error_px: float = 0.0
    average_tag_distance_m: float = 0.0
    image_area_fraction: float = 0.0
    image_spread_fraction: float = 0.0
    distortion_displacement_px: float = 0.0


@dataclass
class TagObservation:
    id: int = 0
    corners_xy_px: list[float] = field(default_factory=list)


@dataclass
class ProcessingTiming:
    capture_to_detect_ms: float = 0.0
    detect_ms: float = 0.0
    solve_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class Observation:
    robot_id: str = ""
    robot_session: str = ""
    service_session: str = ""
    capture_epoch: str = ""
    connection_epoch: int = 0
    sync_epoch: int = 0
    sequence: int = 0
    camera_name: str = ""
    binding_id: str = ""
    binding_generation: int = 0
    manifest_hash: str = ""
    field_hash: str = ""
    calibration_hash: str = ""
    calibration_valid: bool = False
    runtime_generation: str = ""
    mode_id: str = ""
    optical_signature: str = ""
    capture_local_nt_us: int = 0
    timestamp_source: str = ""
    timestamp_uncertainty_s: float = 0.0
    candidates: list[PoseCandidate] = field(default_factory=list)
    tags: list[TagObservation] = field(default_factory=list)
    timing: ProcessingTiming = field(default_factory=ProcessingTiming)
    tag_selection_generation: int = 0
