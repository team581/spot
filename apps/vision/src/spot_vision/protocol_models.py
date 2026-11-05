"""Robot configuration models, which also define spot-config.json's published schema, and
intermediate models for NetworkTables struct construction."""

import math
from dataclasses import dataclass
from dataclasses import field as data_field
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, with_config

from .config import DetectorConfig

# Parsed from JSON only: Spot requires exact JSON types, rejects unknown keys, and checks
# defaults too, so an omitted field cannot slip past a constraint.
CONFIG = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, validate_default=True)
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]


@with_config(CONFIG)
@dataclass
class Pose:
    """Translation in metres (WPILib NWU: +X forward, +Y left, +Z up) and a unit quaternion."""

    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    qw: float = 1.0
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0


Degrees = Annotated[float, Field(ge=-180, le=180)]


@with_config(CONFIG)
@dataclass
class Mount:
    """Camera position on the robot: translation in metres (WPILib NWU: +X forward, +Y left,
    +Z up) and rotation in degrees as WPILib Rotation3d(roll, pitch, yaw). Positive pitch
    points the lens down."""

    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    roll_deg: Degrees = 0.0
    pitch_deg: Degrees = 0.0
    yaw_deg: Degrees = 0.0

    def pose(self) -> Pose:
        from wpimath.geometry import Rotation3d

        q = Rotation3d(
            *(math.radians(v) for v in (self.roll_deg, self.pitch_deg, self.yaw_deg))
        ).getQuaternion()
        return Pose(self.x_m, self.y_m, self.z_m, q.W(), q.X(), q.Y(), q.Z())


@with_config(CONFIG)
@dataclass
class OpticalMode:
    id: Name
    width: Annotated[int, Field(gt=0, le=4096, multiple_of=2)]
    height: Annotated[int, Field(gt=0, le=4096)]
    pixel_format: Literal["YUYV", "MJPEG"]
    fps: Annotated[int, Field(gt=0, le=240)]


@with_config(CONFIG)
@dataclass
class ControlPolicy:
    """A V4L2 control value applied by Spot, such as exposure_time_absolute."""

    name: Name
    default_value: float
    allow_override: Annotated[
        bool, Field(description="Whether the dashboard may change this value.")
    ] = False
    required: Annotated[
        bool, Field(description="Fault the camera if the device lacks this control.")
    ] = False


@with_config(CONFIG)
@dataclass(frozen=True)
class ProcessingPolicy:
    max_fps: Annotated[float, Field(ge=1, le=120)] = 30
    utilization_budget: Annotated[float, Field(ge=0.1, le=0.95)] = 0.8


@with_config(CONFIG)
@dataclass(kw_only=True)
class CameraDefinition:
    name: Name
    required: bool = False
    enabled: bool = True
    robot_to_camera: Mount
    image_rotation_deg: Literal[0, 180] = 0
    allowed_modes: Annotated[
        list[OpticalMode],
        Field(
            min_length=1, max_length=16, description="The first mode is the active capture mode."
        ),
    ]
    controls: Annotated[list[ControlPolicy], Field(max_length=64)] = data_field(
        default_factory=list
    )
    binding_id: Annotated[
        str,
        Field(
            max_length=128,
            description="Physical camera identity. Leave empty and assign it from the dashboard.",
        ),
    ] = ""
    calibration: Annotated[
        dict | None, Field(description="Calibration record applied from the dashboard.")
    ] = None
    timestamp_qualification: Annotated[
        dict | None, Field(description="Timing record applied from the dashboard.")
    ] = None
    detector: DetectorConfig = data_field(default_factory=DetectorConfig)


@with_config(CONFIG)
@dataclass
class FieldTag:
    id: int = 0
    field_to_tag: Pose = data_field(default_factory=Pose)
    size_m: float = 0.0


@with_config(CONFIG)
@dataclass
class FieldLayout:
    origin: str = ""
    length_m: float = 0.0
    width_m: float = 0.0
    tags: list[FieldTag] = data_field(default_factory=list)


Cameras = Annotated[list[CameraDefinition], Field(max_length=32)]


@with_config(CONFIG)
@dataclass
class Profile:
    cameras: Cameras = data_field(default_factory=list)
    field: FieldLayout = data_field(default_factory=FieldLayout)
    max_age_s: float = 0.0
    future_tolerance_s: float = 0.0
    processing: ProcessingPolicy = data_field(default_factory=ProcessingPolicy)


@with_config(CONFIG)
@dataclass
class RobotConfiguration:
    """Robot code's src/main/deploy/spot-config.json."""

    cameras: Cameras = data_field(default_factory=list)
    processing: ProcessingPolicy = data_field(default_factory=ProcessingPolicy)


@with_config(CONFIG)
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
