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


def test_cached_robot_configuration_is_editable_while_disconnected(tmp_path):
    configured(tmp_path)
    restarted = ConfigurationService(StateStore(tmp_path), lambda *_: None)
    restarted.tune("front", {"gain": 3}, restarted.state.generation)
    assert restarted.effective_controls("front")["gain"] == 3


def test_editing_requires_robot_configuration_once(tmp_path):
    service = ConfigurationService(StateStore(tmp_path), lambda *_: None)
    with pytest.raises(ConfigError, match="Connect robot code once"):
        service.configure_document({"cameras": [], "processing": {}}, service.state.generation)


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


def test_override_is_removed_once_robot_code_adopts_it(tmp_path):
    service = configured(tmp_path)
    service.tune("front", {"gain": 7}, service.state.generation)
    changed = manifest()
    changed.profile.cameras[0].controls[0].default_value = 7
    service.accept_manifest(changed)
    assert not service.override_entries()
    restarted = ConfigurationService(StateStore(tmp_path), lambda *_: None)
    assert not restarted.override_entries()
    changed.profile.cameras[0].controls[0].default_value = 9
    service.accept_manifest(changed)
    assert service.effective_controls("front")["gain"] == 9


def test_tuning_back_to_robot_code_value_removes_override(tmp_path):
    service = configured(tmp_path)
    original = service.effective_controls("front")["gain"]
    service.tune("front", {"gain": original + 1}, service.state.generation)
    service.tune("front", {"gain": original}, service.state.generation)
    assert not service.override_entries()


def test_override_flags_robot_code_changes_underneath_it(tmp_path):
    service = configured(tmp_path)
    service.tune("front", {"gain": 7}, service.state.generation)
    [entry] = service.override_entries()
    assert not entry["code_changed"]
    changed = manifest()
    changed.profile.cameras[0].controls[0].default_value = 9
    service.accept_manifest(changed)
    assert service.effective_controls("front")["gain"] == 7
    restarted = ConfigurationService(StateStore(tmp_path), lambda *_: None)
    [entry] = restarted.override_entries()
    assert entry["code_changed"] and entry["code_value"]["default_value"] == 9
    restarted.connection_changed(True)
    restarted.accept_manifest(changed)
    restarted.tune("front", {"gain": 8}, restarted.state.generation)
    assert not restarted.override_entries()[0]["code_changed"]
