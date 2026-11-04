"""Bounded profile and observation validation shared by configuration and transport."""

from __future__ import annotations

import math
import re

from . import protocol_models as wire
from .config import ConfigError
from .protocol import content_hash, restore

MAX_PROFILE_BYTES = 256 * 1024
MAX_CAMERAS = 32  # protocol bound, not a claim about Jetson capacity
MAX_TAGS = 64
MAX_CANDIDATES = 2
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def valid_pose(pose: wire.Pose) -> bool:
    return (
        finite(pose.x_m, pose.y_m, pose.z_m, pose.qw, pose.qx, pose.qy, pose.qz)
        and abs(sum(v * v for v in (pose.qw, pose.qx, pose.qy, pose.qz)) - 1) < 1e-6
    )


def parse_manifest(payload: bytes) -> wire.Manifest:
    if not 0 < len(payload) <= MAX_PROFILE_BYTES:
        raise ConfigError("manifest payload exceeds bounds or is empty")
    try:
        message = restore(wire.Manifest, payload)
    except ValueError as exc:
        raise ConfigError("invalid manifest snapshot") from exc
    validate_manifest(message)
    return message


def validate_manifest(message: wire.Manifest) -> None:
    profile = message.profile
    if not _NAME.fullmatch(profile.robot_id) or not _NAME.fullmatch(message.robot_session):
        raise ConfigError("robot ID and session are required bounded identifiers")
    if message.manifest_hash != content_hash(profile):
        raise ConfigError("manifest content hash mismatch")
    if not finite(profile.max_age_s, profile.future_tolerance_s, profile.reorder_window_s):
        raise ConfigError("timing bounds must be finite")
    if not (
        0 < profile.max_age_s <= 0.25
        and 0 <= profile.future_tolerance_s <= 0.005
        and 0 <= profile.reorder_window_s < profile.max_age_s
    ):
        raise ConfigError("profile timing exceeds observation age/future budgets")
    if len(profile.cameras) > MAX_CAMERAS:
        raise ConfigError("too many camera definitions")
    names: set[str] = set()
    for camera in profile.cameras:
        if not _NAME.fullmatch(camera.name) or camera.name in names:
            raise ConfigError("invalid or duplicate camera name")
        names.add(camera.name)
        if not valid_pose(camera.robot_to_camera):
            raise ConfigError(f"{camera.name}: measured mount transform required")
        if camera.image_rotation_deg not in (0, 180):
            raise ConfigError("image rotation must be 0 or 180 degrees")
        if camera.moving_mount and not _NAME.fullmatch(camera.joint_name):
            raise ConfigError("moving mount requires a joint history name")
        if not 1 <= len(camera.allowed_modes) <= 16:
            raise ConfigError("camera requires 1–16 explicitly allowed optical modes")
        modes: set[str] = set()
        for mode in camera.allowed_modes:
            if not _NAME.fullmatch(mode.id) or mode.id in modes:
                raise ConfigError("invalid or duplicate mode ID")
            modes.add(mode.id)
            if (
                not 0 < mode.width <= 4096
                or not 0 < mode.height <= 4096
                or mode.width % 2
                or not 0 < mode.fps <= 240
                or mode.pixel_format not in ("YUYV", "YUY2", "MJPG", "MJPEG")
                or not _NAME.fullmatch(mode.optical_signature)
            ):
                raise ConfigError("invalid optical mode")
        controls: set[str] = set()
        if len(camera.controls) > 64:
            raise ConfigError("too many control policies")
        for control in camera.controls:
            if (
                not _NAME.fullmatch(control.name)
                or control.name in controls
                or not finite(control.default_value)
            ):
                raise ConfigError("invalid or duplicate control policy")
            controls.add(control.name)
    field = profile.field
    if (
        field.origin != "blue-wall-right"
        or not finite(field.length_m, field.width_m)
        or field.length_m <= 0
        or field.width_m <= 0
        or not 1 <= len(field.tags) <= MAX_TAGS
    ):
        raise ConfigError("complete blue-wall-right field layout required")
    ids: set[int] = set()
    for tag in field.tags:
        if (
            not 0 < tag.id <= 65535
            or tag.id in ids
            or not valid_pose(tag.field_to_tag)
            or not finite(tag.size_m)
            or not 0 < tag.size_m <= 1
        ):
            raise ConfigError("invalid or duplicate field tag")
        ids.add(tag.id)


def validate_observation(message: wire.Observation) -> None:
    if len(message.candidates) > MAX_CANDIDATES or len(message.tags) > MAX_TAGS:
        raise ConfigError("observation candidate/tag count exceeds limit")
    for candidate in message.candidates:
        if (
            not valid_pose(candidate.field_to_camera)
            or candidate.method not in (1, 2)
            or not 1 <= len(candidate.tag_ids) <= MAX_TAGS
            or len(set(candidate.tag_ids)) != len(candidate.tag_ids)
            or not finite(
                candidate.reprojection_error_px,
                candidate.average_tag_distance_m,
                candidate.image_area_fraction,
                candidate.image_spread_fraction,
                candidate.distortion_displacement_px,
            )
            or candidate.reprojection_error_px < 0
            or candidate.average_tag_distance_m <= 0
            or not 0 <= candidate.image_area_fraction <= 1
            or not 0 <= candidate.image_spread_fraction <= 1
        ):
            raise ConfigError("invalid pose candidate")
    if not message.calibration_valid and message.candidates:
        raise ConfigError("uncalibrated observations cannot contain production candidates")
    if len({tag.id for tag in message.tags}) != len(message.tags):
        raise ConfigError("duplicate observed tag ID")
    for tag in message.tags:
        if len(tag.corners_xy_px) != 8 or not finite(*tag.corners_xy_px):
            raise ConfigError("invalid tag corners")
    timing = message.timing
    if (
        not finite(
            timing.capture_to_detect_ms,
            timing.detect_ms,
            timing.solve_ms,
            timing.total_ms,
            message.timestamp_uncertainty_s,
        )
        or min(
            timing.capture_to_detect_ms,
            timing.detect_ms,
            timing.solve_ms,
            timing.total_ms,
            message.timestamp_uncertainty_s,
        )
        < 0
    ):
        raise ConfigError("invalid processing or timestamp uncertainty")
