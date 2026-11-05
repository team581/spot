import json

import pytest

from robot_fixtures import manifest
from spot_vision.config import ConfigError
from spot_vision.contract import parse_manifest, validate_manifest
from spot_vision.protocol import snapshot


def test_complete_manifest_serialization():
    expected = manifest()
    assert parse_manifest(snapshot(expected)) == expected


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: setattr(p, "max_age_s", 0.3),
        lambda p: setattr(p, "future_tolerance_s", 0.01),
        lambda p: p.cameras.append(p.cameras[0]),
        lambda p: setattr(p.field, "origin", ""),
        lambda p: setattr(p.field.tags[0].field_to_tag, "x_m", float("nan")),
    ],
)
def test_invalid_complete_profiles_fail_closed(mutation):
    message = manifest()
    mutation(message.profile)
    with pytest.raises(ConfigError):
        validate_manifest(message)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: setattr(p.cameras[0].allowed_modes[0], "pixel_format", "RGB"),
        lambda p: setattr(p.cameras[0].robot_to_camera, "pitch_deg", 200),
        lambda p: setattr(p.cameras[0], "image_rotation_deg", 90),
        lambda p: setattr(p.cameras[0], "allowed_modes", []),
        lambda p: setattr(p.cameras[0].controls[0], "default_value", "1"),
    ],
)
def test_invalid_camera_fields_fail_when_parsed(mutation):
    message = manifest()
    mutation(message.profile)
    with pytest.raises(ConfigError, match="cameras.0"):
        parse_manifest(snapshot(message))


def test_omitted_camera_fields_use_safe_defaults_but_identity_is_required():
    document = json.loads(snapshot(manifest()))
    camera = document["profile"]["cameras"][0]
    for key in ("required", "enabled", "controls", "binding_id", "calibration", "detector"):
        del camera[key]
    parsed = parse_manifest(json.dumps(document).encode()).profile.cameras[0]
    assert parsed.enabled and not parsed.required and parsed.detector.backend == "cuda"
    del camera["robot_to_camera"]
    with pytest.raises(ConfigError, match="robot_to_camera: Field required"):
        parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize("data", [b"", b"\xff", b"x" * (256 * 1024 + 1)])
def test_profile_payload_bounds_and_malformed(data):
    with pytest.raises(ConfigError):
        parse_manifest(data)


def test_mount_angles_follow_wpilib_with_positive_pitch_pointing_down():
    from wpimath.geometry import Quaternion, Rotation3d, Translation3d

    from spot_vision import protocol_models as wire

    pose = wire.Mount(pitch_deg=30, yaw_deg=90).pose()
    forward = Translation3d(1, 0, 0).rotateBy(
        Rotation3d(Quaternion(pose.qw, pose.qx, pose.qy, pose.qz))
    )
    assert forward.z < 0 and forward.y > 0  # lens tilted down, facing left
