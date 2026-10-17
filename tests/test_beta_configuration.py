import threading

import pytest
from beta_fixtures import manifest

from spot_vision.config import ConfigError
from spot_vision.configuration import ConfigurationService
from spot_vision.persistence import StateStore
from spot_vision.proto import vision_v2_pb2 as wire


def configured(tmp_path):
    service = ConfigurationService(
        StateStore(tmp_path),
        lambda *_: None,
        device_exists=lambda identity: identity in {"usb-a", "usb-b"},
    )
    service.connection_changed(True)
    service.accept_manifest(manifest())
    service.robot_state(wire.RobotState(robot_session="robot-1", enabled=False, sequence=1))
    return service


def test_pinned_code_wins_allowed_tuning_persists_and_cached_hash_is_not_fresh(tmp_path):
    service = configured(tmp_path)
    service.tune("front", {"gain": 5}, service.state.generation)
    assert service.effective_controls("front") == {"gain": 5, "contrast": 16}
    with pytest.raises(ConfigError, match="pinned"):
        service.tune("front", {"contrast": 4}, service.state.generation)
    restarted = ConfigurationService(StateStore(tmp_path), lambda *_: None)
    assert restarted.manifest == service.manifest and not restarted.fresh
    with pytest.raises(ConfigError, match="locked"):
        restarted.require_eligible()
    restarted.connection_changed(True)
    restarted.accept_manifest(manifest())
    assert restarted.fresh and restarted.effective_controls("front")["gain"] == 5


def test_disconnect_does_not_unlock_enabled_robot_and_standalone_is_explicit(tmp_path):
    service = configured(tmp_path)
    service.robot_state(wire.RobotState(robot_session="robot-1", enabled=True, sequence=2))
    service.connection_changed(False)
    with pytest.raises(ConfigError, match="locked"):
        service.rename("usb-a", "front", service.state.generation)
    service.begin_standalone()
    service.rename("usb-a", "front", service.state.generation)
    service.connection_changed(True)
    with pytest.raises(ConfigError, match="locked"):
        service.require_eligible()


def test_device_setup_and_tuning_persist_without_any_robot_profile(tmp_path):
    service = ConfigurationService(StateStore(tmp_path), lambda *_: None,
                                   device_exists=lambda identity: identity == "usb-a")
    mode = {"width": 640, "height": 480, "fps": 120, "pixel_format": "MJPG"}
    service.setup_device("usb-a", mode, {"gain": 10}, service.state.generation)
    service.tune_device("usb-a", {"gain": 11}, service.state.generation)
    assert service.manifest is None and not service.state.data.get("profiles")
    restarted = ConfigurationService(StateStore(tmp_path), lambda *_: None,
                                     device_exists=lambda _: True)
    assert restarted.state.data["standalone_cameras"]["usb-a"]["settings"] == {"gain": 11}
    with pytest.raises(ConfigError, match="locked"):
        restarted.tune_device("usb-a", {"gain": 12}, restarted.state.generation)
    restarted.setup_device("usb-a", mode, {"gain": 99}, restarted.state.generation)
    assert restarted.state.data["standalone_cameras"]["usb-a"]["settings"] == {"gain": 11}
    restarted.tune_device("usb-a", {}, restarted.state.generation, reset=True)
    assert restarted.state.data["standalone_cameras"]["usb-a"]["settings"] == {"gain": 10}


def test_device_setup_cannot_override_robot_binding_or_enable_state(tmp_path):
    service = configured(tmp_path)
    service.rename("usb-a", "front", service.state.generation)
    mode = {"width": 640, "height": 480, "fps": 30, "pixel_format": "MJPG"}
    with pytest.raises(ConfigError, match="robot camera settings"):
        service.setup_device("usb-a", mode, {}, service.state.generation)
    service.robot_state(wire.RobotState(robot_session="robot-1", enabled=True, sequence=2))
    with pytest.raises(ConfigError, match="locked"):
        service.setup_device("usb-b", mode, {}, service.state.generation)


def test_device_tuning_failure_keeps_acknowledged_values_and_generation(tmp_path):
    def apply(state, _):
        if state.data.get("standalone_cameras", {}).get("usb-a", {}).get("settings", {}).get("gain") == 99:
            raise ConfigError("driver rejected gain")

    service = ConfigurationService(StateStore(tmp_path), apply, device_exists=lambda _: True)
    service.setup_device("usb-a", {}, {"gain": 1}, service.state.generation)
    before = service.state
    with pytest.raises(ConfigError, match="driver rejected"):
        service.tune_device("usb-a", {"gain": 99}, before.generation)
    assert service.state == before and service.store.load() == before


def test_bindings_do_not_leak_between_robot_profiles_or_follow_enumeration(tmp_path):
    service = configured(tmp_path)
    service.rename("usb-a", "front", service.state.generation)
    service.accept_manifest(manifest(robot_id="test-other", session="robot-2"))
    assert service.profile_data()["bindings"] == {}
    service.accept_manifest(manifest())
    assert service.profile_data()["bindings"]["front"]["identity"] == "usb-a"


def test_enabled_event_is_seen_during_slow_hardware_apply(tmp_path):
    service = configured(tmp_path)
    old = service.state

    def slow_apply(*_):
        thread = threading.Thread(
            target=service.robot_state,
            args=(wire.RobotState(robot_session="robot-1", enabled=True, sequence=2),),
        )
        thread.start()
        thread.join(1)
        assert not thread.is_alive()

    service._apply = slow_apply
    with pytest.raises(ConfigError, match="locked"):
        service.tune("front", {"gain": 3}, old.generation)
    assert service.store.load() == old
