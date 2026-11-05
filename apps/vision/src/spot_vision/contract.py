"""Bounded profile and observation validation shared by configuration and transport."""

from __future__ import annotations

import math

from . import protocol_models as wire
from .config import ConfigError
from .protocol import restore

MAX_PROFILE_BYTES = 256 * 1024
MAX_TAGS = 64
MAX_CANDIDATES = 2


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
    message = restore(wire.Manifest, payload)
    validate_manifest(message)
    return message


def validate_manifest(message: wire.Manifest) -> None:
    """Check rules that span fields; the models check each field when parsing JSON."""
    profile = message.profile
    if not finite(profile.max_age_s, profile.future_tolerance_s):
        raise ConfigError("timing bounds must be finite")
    if not (0 < profile.max_age_s <= 0.25 and 0 <= profile.future_tolerance_s <= 0.005):
        raise ConfigError("profile timing exceeds observation age/future budgets")
    names: set[str] = set()
    bindings: set[str] = set()
    for camera in profile.cameras:
        if camera.name in names:
            raise ConfigError(f"duplicate camera name {camera.name!r}")
        names.add(camera.name)
        if camera.binding_id:
            if camera.binding_id in bindings:
                raise ConfigError("duplicate physical camera binding")
            bindings.add(camera.binding_id)
        if camera.calibration is not None:
            from .calibration_record import validate_record

            validate_record(camera.calibration)
            if camera.calibration["identity"] != camera.binding_id:
                raise ConfigError("calibration belongs to another camera")
        if camera.timestamp_qualification is not None:
            from .timing_qualification import validate_timing_evidence

            validate_timing_evidence(camera.timestamp_qualification)
            if camera.timestamp_qualification["identity"] != camera.binding_id:
                raise ConfigError("timing qualification belongs to another camera")
        if len({mode.id for mode in camera.allowed_modes}) != len(camera.allowed_modes):
            raise ConfigError(f"{camera.name}: duplicate mode ID")
        if len({control.name for control in camera.controls}) != len(camera.controls):
            raise ConfigError(f"{camera.name}: duplicate control policy")
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
