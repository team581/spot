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
