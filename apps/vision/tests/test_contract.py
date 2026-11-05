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
        lambda p: setattr(p.cameras[0].robot_to_camera, "qw", 0),
        lambda p: p.cameras.append(p.cameras[0]),
        lambda p: setattr(p.cameras[0].allowed_modes[0], "optical_signature", ""),
        lambda p: setattr(p.field, "origin", ""),
        lambda p: setattr(p.field.tags[0].field_to_tag, "x_m", float("nan")),
    ],
)
def test_invalid_complete_profiles_fail_closed(mutation):
    message = manifest()
    mutation(message.profile)
    with pytest.raises(ConfigError):
        validate_manifest(message)


@pytest.mark.parametrize("data", [b"", b"\xff", b"x" * (256 * 1024 + 1)])
def test_profile_payload_bounds_and_malformed(data):
    with pytest.raises(ConfigError):
        parse_manifest(data)
