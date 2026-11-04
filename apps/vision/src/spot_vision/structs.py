"""Numeric WPILib structs shared with the roboRIO.

A frame is one atomic NT value. Tag masks index the ordered, acknowledged field
layout (at most 64 tags), so tag IDs do not need fixed padded arrays per frame.
"""

import hashlib
import struct
from dataclasses import dataclass, field

from wpimath.geometry import Pose3d, Quaternion, Rotation3d, Translation3d
from wpiutil.wpistruct import double, int32, int64, make_wpistruct

from . import protocol_models as data
from .protocol import content_bytes

SOURCES = (
    "",
    "read-completion-local-nt",
    "driver-exposure-start-local-nt",
    "driver-exposure-end-local-nt",
)
SYNC_STATES = ("Waiting", "Synchronized", "Invalid")


@make_wpistruct(name="SpotPoseEstimate")
@dataclass
class PoseEstimate:
    pose: Pose3d = field(default_factory=Pose3d)
    method: int32 = 0
    tagMask: int64 = 0
    reprojectionError: double = 0.0
    averageDistance: double = 0.0
    imageArea: double = 0.0
    imageSpread: double = 0.0
    distortion: double = 0.0


@make_wpistruct(name="SpotFrameResult")
@dataclass
class FrameResult:
    contextHigh: int64 = 0
    contextLow: int64 = 0
    captureHigh: int64 = 0
    captureLow: int64 = 0
    sequence: int64 = 0
    tagSelectionGeneration: int64 = 0
    captureLocalNtUs: int64 = 0
    timestampSource: int32 = 0
    timestampUncertainty: double = 0.0
    observedTags: int64 = 0
    candidateCount: int32 = 0
    primary: PoseEstimate = field(default_factory=PoseEstimate)
    alternate: PoseEstimate = field(default_factory=PoseEstimate)
    captureToDetectMs: double = 0.0
    detectMs: double = 0.0
    solveMs: double = 0.0
    totalMs: double = 0.0


@make_wpistruct(name="SpotRobotStatus")
@dataclass
class RobotStatus:
    sessionHigh: int64 = 0
    sessionLow: int64 = 0
    enabled: bool = False
    sequence: int64 = 0
    selectionGeneration: int64 = 0
    allowedTags: int64 = 0


@make_wpistruct(name="SpotHeartbeat")
@dataclass
class Heartbeat:
    serviceHigh: int64 = 0
    serviceLow: int64 = 0
    runtimeHigh: int64 = 0
    runtimeLow: int64 = 0
    sequence: int64 = 0
    uptime: double = 0.0
    syncState: int32 = 0
    offsetUs: int64 = 0
    syncAge: double = 0.0
    connectionEpoch: int64 = 0
    syncEpoch: int64 = 0
    discontinuities: int64 = 0


@make_wpistruct(name="SpotFieldTag")
@dataclass
class FieldTag:
    id: int32 = 0
    pose: Pose3d = field(default_factory=Pose3d)
    size: double = 0.0


def token(value: str) -> tuple[int, int]:
    return struct.unpack("<qq", hashlib.sha256(value.encode()).digest()[:16])


def frame_context(ack: data.Acknowledgement, camera_name: str) -> tuple[int, int]:
    return struct.unpack(
        "<qq", hashlib.sha256(content_bytes(ack) + camera_name.encode()).digest()[:16]
    )


def signed_mask(mask: int) -> int:
    return mask if mask < 1 << 63 else mask - (1 << 64)


def tag_mask(ids, layout: data.FieldLayout) -> int:
    indices = {tag.id: index for index, tag in enumerate(layout.tags)}
    mask = 0
    for tag_id in ids:
        mask |= 1 << indices[tag_id]
    return signed_mask(mask)


def tag_ids(mask: int, layout: data.FieldLayout) -> list[int]:
    unsigned = mask & ((1 << 64) - 1)
    if unsigned >> len(layout.tags):
        raise ValueError("tag mask exceeds acknowledged field layout")
    return [tag.id for index, tag in enumerate(layout.tags) if unsigned & (1 << index)]


def pose_value(pose: data.Pose) -> Pose3d:
    return Pose3d(
        Translation3d(pose.x_m, pose.y_m, pose.z_m),
        Rotation3d(Quaternion(pose.qw, pose.qx, pose.qy, pose.qz)),
    )


def pose_model(pose) -> data.Pose:
    q = pose.rotation().getQuaternion()
    return data.Pose(pose.X(), pose.Y(), pose.Z(), q.W(), q.X(), q.Y(), q.Z())


def result_value(
    observation: data.Observation, context: tuple[int, int], layout: data.FieldLayout
) -> FrameResult:
    if len(observation.candidates) > 2:
        raise ValueError("frame exceeds two pose candidates")
    estimates = [
        PoseEstimate(
            pose_value(candidate.field_to_camera),
            candidate.method,
            tag_mask(candidate.tag_ids, layout),
            candidate.reprojection_error_px,
            candidate.average_tag_distance_m,
            candidate.image_area_fraction,
            candidate.image_spread_fraction,
            candidate.distortion_displacement_px,
        )
        for candidate in observation.candidates
    ]
    estimates += [PoseEstimate() for _ in range(2 - len(estimates))]
    timing = observation.timing
    return FrameResult(
        *context,
        *token(observation.capture_epoch),
        observation.sequence,
        observation.tag_selection_generation,
        observation.capture_local_nt_us,
        SOURCES.index(observation.timestamp_source),
        observation.timestamp_uncertainty_s,
        tag_mask(
            [
                tag.id
                for tag in observation.tags
                if tag.id in {field_tag.id for field_tag in layout.tags}
            ],
            layout,
        ),
        len(observation.candidates),
        *estimates,
        timing.capture_to_detect_ms,
        timing.detect_ms,
        timing.solve_ms,
        timing.total_ms,
    )
