"""Robot defaults and persistent dashboard overrides."""

from __future__ import annotations

import copy
import json
import math
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from . import config_overrides as overlay
from . import protocol_models as wire
from .config import ConfigError
from .contract import parse_manifest, validate_manifest
from .persistence import StateSnapshot, StateStore, canonical_bytes, durable_replace
from .protocol import restore, snapshot


def mode_signature(mode: wire.OpticalMode) -> str:
    # Calibration can be performed before assigning a robot role. Logical mode IDs
    # and pixel-format aliases must not change the physical calibration identity.
    pixel_format = "MJPG" if mode.pixel_format in {"MJPG", "MJPEG"} else "YUYV"
    return f"{mode.width}x{mode.height}-{mode.fps}-{pixel_format}"


def optical_controls(values: dict) -> dict:
    """Controls whose changes alter the calibrated rays or pixel coordinates."""
    return {
        name: value
        for name, value in values.items()
        if any(
            word in name for word in ("focus", "zoom", "crop", "rotate", "flip", "pan_", "tilt_")
        )
    }


@dataclass(frozen=True)
class TagSelection:
    generation: int
    allowed_tag_ids: tuple[int, ...]


class ConfigurationService:
    def __init__(
        self,
        store: StateStore,
        apply: Callable[[StateSnapshot, wire.Manifest | None], None],
        *,
        device_exists: Callable[[str], bool] = lambda _: False,
        supported_controls: Callable[[str], set[str] | None] = lambda _: None,
    ) -> None:
        self.store, self._apply = store, apply
        self.overrides_path = store.root / "dashboard-overrides.json"
        self.baseline_path = store.root / "robot-config.json"
        self.overrides = (
            json.loads(self.overrides_path.read_bytes()) if self.overrides_path.exists() else {}
        )
        if not isinstance(self.overrides, dict):
            raise ConfigError("Dashboard overrides must be an object")
        self.robot_manifest: wire.Manifest | None = None
        self._device_exists = device_exists
        self._supported_controls = supported_controls
        self._lock = threading.RLock()
        self._eligibility_lock = threading.RLock()
        self._connection_version = 0
        self.state = store.load()
        self.manifest: wire.Manifest | None = None
        self.fresh = False
        self.connected = False
        self.standalone = False
        self._selection: TagSelection | None = None
        self.applied_generation = ""
        self._load_cached_manifest()

    def _load_cached_manifest(self) -> None:
        if self.baseline_path.exists():
            self.robot_manifest = parse_manifest(self.baseline_path.read_bytes())
            self.manifest = self._effective(self.robot_manifest, self.overrides)

    @staticmethod
    def _effective(baseline: wire.Manifest, overrides: dict) -> wire.Manifest:
        original = wire.RobotConfiguration(baseline.profile.cameras, baseline.profile.processing)
        document = overlay.merge(overlay.values(original), overrides)
        names = {camera.name for camera in original.cameras}
        document["cameras"] = {
            name: camera for name, camera in document["cameras"].items() if name in names
        }
        settings = overlay.settings(document)
        result = replace(
            baseline,
            profile=replace(
                baseline.profile, cameras=settings.cameras, processing=settings.processing
            ),
        )
        validate_manifest(result)
        return result

    def connection_changed(self, connected: bool) -> None:
        # Link changes must be observable during hardware reconfiguration.
        with self._eligibility_lock:
            self._connection_version += 1
            self.connected = connected
            self.fresh = False
            self.applied_generation = ""
            self._selection = None
            if connected:
                self.standalone = False

    def robot_state(self, state: wire.RobotState) -> None:
        with self._eligibility_lock:
            manifest = self.robot_manifest
            if manifest is None:
                return
            ids = tuple(state.allowed_tag_ids)
            known = {tag.id for tag in manifest.profile.field.tags}
            if (
                state.tag_selection_generation > 0
                and ids == tuple(sorted(set(ids)))
                and set(ids) <= known
            ):
                self._selection = TagSelection(state.tag_selection_generation, ids)

    def tag_selection(self) -> TagSelection | None:
        with self._eligibility_lock:
            return self._selection if self.connected and self.fresh else None

    def require_eligible(self) -> None:
        if self.connected or self.standalone:
            return
        raise ConfigError("Connect robot code or begin standalone setup")

    def begin_standalone(self) -> None:
        with self._eligibility_lock:
            if self.connected:
                raise ConfigError("standalone setup requires a known disconnected robot link")
            self.standalone = True

    def _unbound_device(self, identity: str) -> None:
        if not self._device_exists(identity):
            raise ConfigError("camera is disconnected")
        if self.manifest and any(c.binding_id == identity for c in self.manifest.profile.cameras):
            raise ConfigError("Use robot camera settings for a configured camera")

    def setup_device(self, identity: str, mode: dict, defaults: dict, expected: str):
        with self._lock:
            self._unbound_device(identity)
            if not self.connected:
                self.begin_standalone()
            self.require_eligible()
            data = copy.deepcopy(self.state.data)
            devices = data.setdefault("standalone_cameras", {})
            if identity not in devices and len(devices) >= 128:
                raise ConfigError("Standalone camera setup limit reached")
            devices.setdefault(
                identity,
                {
                    "mode": copy.deepcopy(mode),
                    "settings": dict(defaults),
                    "defaults": dict(defaults),
                },
            )
            return self._commit(data, expected)

    def tune_device(self, identity: str, values: dict, expected: str, *, reset=False):
        with self._lock:
            self.require_eligible()
            self._unbound_device(identity)
            data = copy.deepcopy(self.state.data)
            entry = data.get("standalone_cameras", {}).get(identity)
            if entry is None:
                raise ConfigError("Open standalone camera setup first")
            if reset:
                values = entry["defaults"]
            supported = self._supported_controls(identity)
            if not isinstance(values, dict) or not values or len(values) > 64:
                raise ConfigError("empty or oversized tuning request")
            for key, value in values.items():
                if supported is not None and key not in supported:
                    raise ConfigError(f"{key}: unavailable on the connected device")
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ConfigError(f"{key}: numeric value required")
            previous = optical_controls(entry["settings"])
            entry["settings"].update(values)
            if optical_controls(entry["settings"]) != previous:
                data["calibrations"] = {
                    key: record
                    for key, record in data.get("calibrations", {}).items()
                    if record["identity"] != identity
                }
            return self._commit(data, expected)

    def set_device_mode(self, identity: str, mode: dict, expected: str):
        with self._lock:
            self.require_eligible()
            self._unbound_device(identity)
            data = copy.deepcopy(self.state.data)
            entry = data.get("standalone_cameras", {}).get(identity)
            if entry is None:
                raise ConfigError("Open standalone camera setup first")
            entry["mode"] = mode
            return self._commit(data, expected)

    def _activate(
        self,
        data: dict,
        target: wire.Manifest | None,
        *,
        code: bool = False,
        overrides: dict | None = None,
    ) -> StateSnapshot:
        old_state, old_manifest = self.state, self.manifest
        version = self._connection_version

        def eligible():
            if code:
                if not self.connected or version != self._connection_version:
                    raise ConfigError("Robot connection changed while applying configuration")
            else:
                self.require_eligible()

        eligible()
        persistent = copy.deepcopy(data)
        saved = self.store.load()
        if persistent != saved.data:
            state = self.store.commit(
                persistent,
                saved.generation,
                apply=lambda candidate: self._apply(candidate, target),
                rollback=lambda _: self._apply(old_state, old_manifest),
                eligible=eligible,
            )
        else:
            state = StateSnapshot(uuid.uuid4().hex, copy.deepcopy(data))
            try:
                self._apply(state, target)
                eligible()
            except Exception:
                self._apply(old_state, old_manifest)
                raise
        if overrides is not None:
            try:
                durable_replace(self.overrides_path, canonical_bytes(overrides))
            except OSError:
                self._apply(old_state, old_manifest)
                raise
            self.overrides = overrides
        self.state = StateSnapshot(state.generation, copy.deepcopy(data))
        self.manifest = target
        self.applied_generation = state.generation
        return self.state

    def _commit(self, data: dict, expected: str) -> StateSnapshot:
        if expected != self.state.generation:
            raise ConfigError("revision conflict; fetch current configuration")
        if self.manifest is not None and self.fresh:
            return self._configure(self.export_configuration(data), expected, data)
        return self._activate(data, self.manifest)

    def accept_manifest(self, manifest: wire.Manifest) -> StateSnapshot:
        validate_manifest(manifest)
        with self._lock:
            if not self.connected:
                raise ConfigError("Robot config requires an NT connection")
            changed = manifest != self.robot_manifest
            self.robot_manifest = copy.deepcopy(manifest)
            target = self._effective(manifest, self.overrides)
            if self.fresh and target == self.manifest:
                if changed:
                    durable_replace(self.baseline_path, snapshot(manifest))
                return self.state
            state = self._activate(self.state.data, target, code=True)
            durable_replace(self.baseline_path, snapshot(manifest))
            self.fresh = True
            self._selection = None
            return state

    def export_configuration(self, data: dict | None = None) -> wire.RobotConfiguration:
        if self.manifest is None:
            raise ConfigError("Connect robot code before exporting its configuration")
        data = self.state.data if data is None else data
        cameras = copy.deepcopy(self.manifest.profile.cameras)
        for camera in cameras:
            identity = camera.binding_id
            mode = camera.allowed_modes[0]
            record = data.get("calibrations", {}).get(identity + ":" + mode_signature(mode))
            # Calibration edits are explicit; saved standalone results are not defaults.
            if data is not self.state.data:
                old = self.state.data.get("calibrations", {}).get(
                    identity + ":" + mode_signature(mode)
                )
                if record != old:
                    camera.calibration = copy.deepcopy(record)
                timing = data.get("timestamp_qualifications", {}).get(identity)
                if timing != self.state.data.get("timestamp_qualifications", {}).get(identity):
                    camera.timestamp_qualification = copy.deepcopy(timing)
        return wire.RobotConfiguration(cameras, copy.deepcopy(self.manifest.profile.processing))

    def _configure(
        self, settings: wire.RobotConfiguration, expected: str, data: dict
    ) -> StateSnapshot:
        self.require_eligible()
        if expected != self.state.generation:
            raise ConfigError("revision conflict; fetch current configuration")
        baseline = self.robot_manifest
        current = self.manifest
        if baseline is None or current is None or not self.fresh:
            raise ConfigError("Connect robot code before editing camera settings")
        if [c.name for c in settings.cameras] != [c.name for c in baseline.profile.cameras]:
            raise ConfigError("Change camera names and order in robot code")
        validate_manifest(
            replace(
                current,
                profile=replace(
                    current.profile, cameras=settings.cameras, processing=settings.processing
                ),
            )
        )
        overrides = copy.deepcopy(self.overrides)
        before = overlay.values(
            wire.RobotConfiguration(current.profile.cameras, current.profile.processing)
        )
        delta = overlay.changes(before, overlay.values(settings))
        # Existing overrides stay saved even when a new baseline matches their value.
        overrides = overlay.merge(overrides, delta)
        target = self._effective(baseline, overrides)
        return self._activate(data, target, overrides=overrides)

    def configure(self, settings: wire.RobotConfiguration, expected: str) -> StateSnapshot:
        with self._lock:
            return self._configure(settings, expected, self.state.data)

    def override_entries(self) -> list[dict]:
        if self.robot_manifest is None:
            return []
        return overlay.entries(self.overrides)

    def clear_overrides(self, expected: str, path: str = "") -> StateSnapshot:
        with self._lock:
            if expected != self.state.generation:
                raise ConfigError("revision conflict; fetch current configuration")
            if self.robot_manifest is None:
                raise ConfigError("Connect robot code before clearing overrides")
            overrides = copy.deepcopy(self.overrides)
            overrides = overlay.clear(overrides, path)
            target = self._effective(self.robot_manifest, overrides)
            return self._activate(self.state.data, target, overrides=overrides)

    def configure_document(self, document: dict, expected: str) -> StateSnapshot:
        try:
            settings = restore(wire.RobotConfiguration, json.dumps(document).encode())
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        return self.configure(settings, expected)

    def camera(self, name: str) -> wire.CameraDefinition:
        if self.manifest is not None:
            for camera in self.manifest.profile.cameras:
                if camera.name == name:
                    return camera
        raise ConfigError("camera name is not configured in robot code")

    def rename(self, identity: str, name: str, expected: str) -> StateSnapshot:
        with self._lock:
            if not self._device_exists(identity):
                raise ConfigError("Camera is disconnected; confirm its preview")
            settings = self.export_configuration()
            camera = next(c for c in settings.cameras if c.name == name)
            if camera.binding_id == identity:
                return self._configure(settings, expected, self.state.data)
            if camera.binding_id:
                raise ConfigError("Camera name already belongs to another device")
            for other in settings.cameras:
                if other.binding_id == identity:
                    other.binding_id = ""
                    other.calibration = other.timestamp_qualification = None
            camera.binding_id = identity
            camera.calibration = camera.timestamp_qualification = None
            return self._configure(settings, expected, self.state.data)

    def replace_camera(
        self, name: str, expected: str, *, identity: str | None = None
    ) -> StateSnapshot:
        with self._lock:
            settings = self.export_configuration()
            camera = next(c for c in settings.cameras if c.name == name)
            identity = identity or camera.binding_id
            if not identity or not self._device_exists(identity):
                raise ConfigError("Replacement camera is disconnected; confirm its preview")
            camera.binding_id = identity
            camera.calibration = camera.timestamp_qualification = None
            return self._configure(settings, expected, self.state.data)

    def tune(
        self, name: str, values: dict[str, float], expected: str, *, reset: bool = False
    ) -> StateSnapshot:
        with self._lock:
            if reset:
                return self.clear_overrides(expected, "cameras/" + name + "/controls")
            settings = self.export_configuration()
            camera = next(c for c in settings.cameras if c.name == name)
            policies = {control.name: control for control in camera.controls}
            supported = self._supported_controls(name)
            if not values or len(values) > 64:
                raise ConfigError("Empty or oversized tuning request")
            for key, value in values.items():
                if supported is not None and key not in supported:
                    raise ConfigError(f"{key}: unavailable on the connected device")
                if key in policies and not policies[key].allow_override:
                    raise ConfigError(f"{key}: pinned by robot policy")
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ConfigError(f"{key}: numeric value required")
                if key in policies:
                    policies[key].default_value = float(value)
                else:
                    camera.controls.append(wire.ControlPolicy(key, float(value), True, False))
            if optical_controls(self.effective_controls(name)) != optical_controls(
                {c.name: c.default_value for c in camera.controls}
            ):
                camera.calibration = camera.timestamp_qualification = None
            return self._configure(settings, expected, self.state.data)

    def effective_controls(self, name: str) -> dict[str, float]:
        return {c.name: c.default_value for c in self.camera(name).controls}

    def set_mode(self, name: str, mode_id: str, expected: str) -> StateSnapshot:
        with self._lock:
            settings = self.export_configuration()
            camera = next(c for c in settings.cameras if c.name == name)
            if mode_id not in {mode.id for mode in camera.allowed_modes}:
                raise ConfigError("Mode is not allowed by robot code")
            camera.allowed_modes.sort(key=lambda mode: mode.id != mode_id)
            return self._configure(settings, expected, self.state.data)

    def import_data(
        self,
        document: dict,
        expected: str,
        validate: Callable[[dict], None],
        validate_timing_record: Callable[[dict], None],
    ) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            if (
                not isinstance(document, dict)
                or set(document) != {"schema_version", "data"}
                or document["schema_version"] != 1
            ):
                raise ConfigError("Unsupported configuration export schema")
            incoming = document["data"]
            if not isinstance(incoming, dict) or set(incoming) - {
                "calibrations",
                "calibration_options",
                "timestamp_qualifications",
                "standalone_cameras",
            }:
                raise ConfigError("Unknown imported state fields")
            data = copy.deepcopy(self.state.data)
            for key, record in incoming.get("calibrations", {}).items():
                validate(record)
                if key != record["identity"] + ":" + record["mode_signature"]:
                    raise ConfigError("Imported calibration identity/key mismatch")
            data["calibrations"] = copy.deepcopy(incoming.get("calibrations", {}))
            for key, record in incoming.get("timestamp_qualifications", {}).items():
                validate_timing_record(record)
                if key != record["identity"]:
                    raise ConfigError("Imported timing identity/key mismatch")
            data["timestamp_qualifications"] = copy.deepcopy(
                incoming.get("timestamp_qualifications", {})
            )
            # Board options are captured separately through their validated UI
            # path; import does not alter an in-progress calibration session.
            return self._commit(data, expected)

    def qualify_timing(
        self, record: dict, expected: str, validate: Callable[[dict], None]
    ) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            validate(record)
            data = copy.deepcopy(self.state.data)
            data.setdefault("timestamp_qualifications", {})[record["identity"]] = copy.deepcopy(
                record
            )
            return self._commit(data, expected)

    def calibration_group(
        self, records: list[dict], expected: str, validate: Callable[[dict], None]
    ) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            if not records or len(records) > 32:
                raise ConfigError("select a non-empty bounded calibration group")
            data = copy.deepcopy(self.state.data)
            calibrations = data.setdefault("calibrations", {})
            keys: set[str] = set()
            for record in records:
                validate(record)
                key = record["identity"] + ":" + record["mode_signature"]
                if key in keys:
                    raise ConfigError("duplicate selected calibration")
                keys.add(key)
                stored = copy.deepcopy(record)
                stored["id"] = uuid.uuid4().hex
                calibrations[key] = stored
            if (
                self.manifest is not None
                and self.fresh
                and any(
                    camera.binding_id == record["identity"]
                    for camera in self.manifest.profile.cameras
                    for record in records
                )
            ):
                settings = self.export_configuration(data)
                for camera in settings.cameras:
                    for record in records:
                        if camera.binding_id == record["identity"]:
                            camera.calibration = copy.deepcopy(
                                data["calibrations"][
                                    record["identity"] + ":" + record["mode_signature"]
                                ]
                            )
                return self._configure(settings, expected, data)
            return self._commit(data, expected)

    def restore(
        self,
        generation: str,
        expected: str,
        validate: Callable[[dict], None],
        identities: list[str] | None = None,
        calibration_ids: list[str] | None = None,
    ) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            old = self.store.read_generation(generation)
            # Restore calibration results while retaining current bindings and capture settings.
            records = {
                key: value
                for key, value in old.data.get("calibrations", {}).items()
                if (identities is None or value["identity"] in identities)
                and (calibration_ids is None or value.get("id") in calibration_ids)
            }
            if not records or (
                identities is not None
                and set(identities) - {r["identity"] for r in records.values()}
            ):
                raise ConfigError("Selected history group is empty or unavailable")
            if calibration_ids is not None and (
                not calibration_ids
                or set(calibration_ids) - {r.get("id") for r in records.values()}
            ):
                raise ConfigError("Selected calibration records are empty or unavailable")
            for calibration in records.values():
                validate(calibration)
            data = copy.deepcopy(self.state.data)
            data.setdefault("calibrations", {}).update(copy.deepcopy(records))
            if self.manifest is not None and self.fresh:
                settings = self.export_configuration(data)
                changed = False
                for camera in settings.cameras:
                    record = records.get(
                        camera.binding_id + ":" + mode_signature(camera.allowed_modes[0])
                    )
                    if record is not None:
                        camera.calibration = copy.deepcopy(record)
                        changed = True
                if changed:
                    return self._configure(settings, expected, data)
            return self._commit(data, expected)
