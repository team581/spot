import copy

import pytest

from robot_fixtures import manifest
from spot_vision.config import ConfigError
from spot_vision.configuration import ConfigurationService
from spot_vision.persistence import StateStore


def configured(tmp_path):
    service = ConfigurationService(
        StateStore(tmp_path),
        lambda *_: None,
        device_exists=lambda identity: identity in {"usb-a", "usb-b"},
    )
    service.connection_changed(True)
    service.accept_manifest(manifest())
    return service


def test_dashboard_overrides_survive_restart_and_deployment_until_cleared(tmp_path):
    service = configured(tmp_path)
    service.tune("front", {"gain": 5}, service.state.generation)
    with pytest.raises(ConfigError, match="pinned"):
        service.tune("front", {"contrast": 4}, service.state.generation)
    changed = manifest()
    changed.profile.cameras[0].controls[0].default_value = 9
    changed.profile.cameras[0].controls[1].default_value = 20
    service.accept_manifest(changed)
    assert service.effective_controls("front") == {"gain": 5, "contrast": 20}
    restarted = ConfigurationService(StateStore(tmp_path), lambda *_: None)
    assert restarted.manifest == service.manifest and not restarted.fresh
    restarted.connection_changed(True)
    restarted.accept_manifest(changed)
    restarted.clear_overrides(restarted.state.generation, "cameras/front/controls/gain")
    assert restarted.effective_controls("front")["gain"] == 9
    assert not restarted.override_entries()


def test_configuration_edits_do_not_require_disabled_state(tmp_path):
    service = configured(tmp_path)
    service.rename("usb-a", "front", service.state.generation)
    service.tune("front", {"gain": 3}, service.state.generation)
    assert service.camera("front").binding_id == "usb-a"
    assert service.effective_controls("front")["gain"] == 3
    assert not list(service.store.generations.glob("*.json"))


def test_device_setup_and_tuning_persist_without_robot_configuration(tmp_path):
    service = ConfigurationService(
        StateStore(tmp_path), lambda *_: None, device_exists=lambda _: True
    )
    mode = {"width": 640, "height": 480, "fps": 120, "pixel_format": "MJPG"}
    service.setup_device("usb-a", mode, {"gain": 10}, service.state.generation)
    service.tune_device("usb-a", {"gain": 11}, service.state.generation)
    restarted = ConfigurationService(
        StateStore(tmp_path), lambda *_: None, device_exists=lambda _: True
    )
    assert restarted.state.data["standalone_cameras"]["usb-a"]["settings"] == {"gain": 11}
    with pytest.raises(ConfigError, match="Connect"):
        restarted.tune_device("usb-a", {"gain": 12}, restarted.state.generation)
    restarted.setup_device("usb-a", mode, {"gain": 99}, restarted.state.generation)
    restarted.tune_device("usb-a", {}, restarted.state.generation, reset=True)
    assert restarted.state.data["standalone_cameras"]["usb-a"]["settings"] == {"gain": 10}


def test_device_setup_cannot_override_bound_camera(tmp_path):
    service = configured(tmp_path)
    service.rename("usb-a", "front", service.state.generation)
    with pytest.raises(ConfigError, match="robot camera settings"):
        service.setup_device("usb-a", {}, {}, service.state.generation)


def test_rejected_apply_keeps_saved_overrides_and_effective_settings(tmp_path):
    service = configured(tmp_path)
    service.tune("front", {"gain": 2}, service.state.generation)
    before, saved = service.state, service.overrides_path.read_bytes()
    original = copy.deepcopy(service.manifest)

    def apply(_, candidate):
        if candidate.profile.cameras[0].controls[0].default_value == 99:
            raise ConfigError("driver rejected gain")

    service._apply = apply
    with pytest.raises(ConfigError, match="driver rejected"):
        service.tune("front", {"gain": 99}, before.generation)
    assert service.state == before and service.manifest == original
    assert service.overrides_path.read_bytes() == saved


def test_explicit_override_is_retained_even_if_new_defaults_match(tmp_path):
    service = configured(tmp_path)
    service.tune("front", {"gain": 7}, service.state.generation)
    changed = manifest()
    changed.profile.cameras[0].controls[0].default_value = 7
    service.accept_manifest(changed)
    assert service.override_entries()
    changed.profile.cameras[0].controls[0].default_value = 9
    service.accept_manifest(changed)
    assert service.effective_controls("front")["gain"] == 7
