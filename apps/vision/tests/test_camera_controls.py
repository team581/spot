import pytest

from spot_vision import camera_controls as module
from spot_vision.devices import parse_capability_controls


@pytest.mark.parametrize(
    "fps,hardware_max,expected",
    [
        (120, 1_000_000, 8300),
        (30, 1_000_000, 33300),
        (120, 7000, 7000),
    ],
)
def test_exposure_range_fits_capture_interval_and_driver_steps(fps, hardware_max, expected):
    control = {
        "name": "exposure_time_absolute",
        "min": 5000,
        "max": hardware_max,
        "step": 100,
        "value": 5000,
        "allowed": True,
    }
    result = module.frame_limited_exposure(control, fps)
    assert result["max"] == expected and result["hardware_max"] == hardware_max
    assert result["exposure_limit_available"]
    assert control["max"] == hardware_max and result["value"] == 5000


def test_no_valid_exposure_does_not_invent_a_value_below_device_minimum():
    result = module.frame_limited_exposure(
        {"name": "exposure_absolute", "min": 5000, "max": 1_000_000, "step": 100}, 210
    )
    assert result["max"] == 5000 and not result["exposure_limit_available"]
    assert not result["allowed"] and "lower capture rate" in result["reason"]


ARDUCAM = """
 brightness 0x00980900 (int) : min=-64 max=64 step=1 default=0 value=0
 gain 0x00980913 (int) : min=0 max=100 step=1 default=0 value=20
 white_balance_automatic 0x0098090c (bool) : default=1 value=1
 white_balance_temperature 0x0098091a (int) : min=2800 max=6500 step=1 default=4600 value=4600 flags=inactive
 auto_exposure 0x009a0901 (menu) : min=0 max=3 default=3 value=1 (Manual Mode)
    1: Manual Mode
    3: Aperture Priority Mode
 exposure_time_absolute 0x009a0902 (int) : min=1 max=5000 step=1 default=157 value=10
 exposure_dynamic_framerate 0x009a0903 (bool) : default=0 value=0
"""
SWIFT = ARDUCAM.replace("min=1 max=5000", "min=50 max=10000").replace(
    "default=157 value=10", "default=166 value=50"
)


def test_discovery_uses_actual_camera_ranges_units_flags_and_sparse_menus():
    controls = {c["name"]: c for c in parse_capability_controls(ARDUCAM)}
    assert controls["brightness"]["label"] == "Black level / brightness"
    assert controls["brightness"]["min"] == -64
    assert controls["exposure_time_absolute"]["factor"] == 100
    assert controls["exposure_time_absolute"]["value"] == 10
    assert not controls["white_balance_temperature"]["writable"]
    assert [o["value"] for o in controls["auto_exposure"]["options"]] == [1, 3]
    swift = {c["name"]: c for c in parse_capability_controls(SWIFT)}
    assert swift["exposure_time_absolute"]["min"] * 100 == 5000
