from types import SimpleNamespace

import pytest

from spot_vision import camera_controls as module


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
    controls = {c["name"]: c for c in module.parse_controls(ARDUCAM)}
    assert controls["brightness"]["label"] == "Black level / brightness"
    assert controls["brightness"]["min"] == -64
    assert controls["exposure_time_absolute"]["factor"] == 100
    assert controls["exposure_time_absolute"]["value"] == 10
    assert not controls["white_balance_temperature"]["writable"]
    assert [o["value"] for o in controls["auto_exposure"]["options"]] == [1, 3]
    assert "exposure_dynamic_framerate" not in controls  # Arducam uses this for trigger mode.
    swift = {c["name"]: c for c in module.parse_controls(SWIFT)}
    assert swift["exposure_time_absolute"]["min"] * 100 == 5000
    auto = module.parse_controls(ARDUCAM.replace("value=1 (Manual Mode)", "value=3"))
    assert not next(c for c in auto if c["name"] == "exposure_time_absolute")["writable"]


def fake_camera(monkeypatch, initial=ARDUCAM):
    state = {"output": initial, "writes": []}

    def run(device, argument):
        assert device == "/dev/video6"
        if argument.startswith("--set-ctrl="):
            name, value = argument.removeprefix("--set-ctrl=").split("=")
            state["writes"].append((name, int(value)))
            state["output"] = "\n".join(
                module.re.sub(r"value=-?\d+", "value=" + value, line)
                if line.strip().startswith(name + " ")
                else line
                for line in state["output"].splitlines()
            )
        return state["output"]

    monkeypatch.setattr(module, "_run", run)
    controls = module.CameraControls(SimpleNamespace())
    monkeypatch.setattr(controls, "_device", lambda: "/dev/video6")
    return controls, state


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("brightness", 65),
        ("brightness", True),
        ("brightness", 1.5),
        ("auto_exposure", 2),
        ("white_balance_temperature", 4600),
        ("exposure_dynamic_framerate", 1),
        ("not_a_control", 1),
    ],
)
def test_invalid_or_inactive_controls_never_write(monkeypatch, name, value):
    controls, state = fake_camera(monkeypatch)
    with pytest.raises(ValueError):
        controls.set(name, value)
    assert state["writes"] == []


def test_step_validation_uses_camera_specific_step(monkeypatch):
    controls, state = fake_camera(
        monkeypatch, SWIFT.replace("step=1 default=0 value=0", "step=2 default=0 value=0")
    )
    with pytest.raises(ValueError, match="step"):
        controls.set("brightness", 1)
    assert not state["writes"]


def test_verified_overrides_reapply_mode_before_exposure_on_reconnect(monkeypatch):
    controls, state = fake_camera(monkeypatch)
    controls.set("exposure_time_absolute", 30)
    controls.set("brightness", -12)
    controls.set("auto_exposure", 1)
    state["output"] = ARDUCAM
    state["writes"] = []
    controls.reapply("/dev/video6")
    assert state["writes"] == [
        ("auto_exposure", 1),
        ("exposure_time_absolute", 30),
        ("brightness", -12),
    ]


def test_failed_write_does_not_become_reconnect_override(monkeypatch):
    controls, _ = fake_camera(monkeypatch)
    monkeypatch.setattr(module, "_run", lambda *args: ARDUCAM)
    with pytest.raises(module.ControlError, match="retain"):
        controls.set("brightness", 12)
    assert controls.overrides == {}


def test_command_timeout_is_a_control_error(monkeypatch):
    def timeout(*args, **kwargs):
        raise module.subprocess.TimeoutExpired("v4l2-ctl", 3)

    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(module.ControlError, match="unavailable"):
        module._run("/dev/video6", "--list-ctrls-menus")
