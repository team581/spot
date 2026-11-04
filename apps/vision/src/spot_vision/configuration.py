"""Robot authority, setup eligibility and acknowledged generation mutations."""

from __future__ import annotations

import base64
import copy
import hashlib
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import protocol_models as wire
from .beta_contract import content_hash, parse_manifest, validate_manifest
from .config import ConfigError
from .persistence import StateSnapshot, StateStore, canonical_bytes
from .protocol import snapshot


def mode_signature(mode: wire.OpticalMode) -> str:
    return content_hash(mode)


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
        state_expiry_s: float = 2.0,
        device_exists: Callable[[str], bool] = lambda _: False,
        supported_controls: Callable[[str], set[str] | None] = lambda _: None,
    ) -> None:
        self.store, self._apply = store, apply
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
        self._robot_state: wire.RobotState | None = None
        self._robot_updated = float("-inf")
        self._state_expiry = state_expiry_s
        self.acknowledged_generation = ""
        self._load_cached_manifest()

    def _load_cached_manifest(self) -> None:
        robot_id = self.state.data.get("active_robot")
        cached = self.state.data.get("profiles", {}).get(robot_id, {}).get("manifest")
        if cached:
            try:
                self.manifest = parse_manifest(base64.b64decode(cached, validate=True))
            except (ConfigError, ValueError) as exc:
                self.store.fault = f"Invalid cached profile: {exc}"
                self.manifest = None

    def connection_changed(self, connected: bool) -> None:
        # Independent of the configuration lock: robot enable/link events must
        # be observable while a slow hardware transaction is in progress.
        with self._eligibility_lock:
            self._connection_version += 1
            self.connected = connected
            self.fresh = False
            self.acknowledged_generation = ""
            self._selection = None
            self._selection_valid = False
            self._robot_state = None
            self._robot_updated = float("-inf")
            if connected:
                self.standalone = False

    def robot_state(self, state: wire.RobotState, now: float | None = None) -> None:
        with self._eligibility_lock:
            if (
                state.sequence == 0
                or not self.connected
                or not self.fresh
                or self.manifest is None
                or state.robot_session != self.manifest.robot_session
            ):
                return
            if self._robot_state is not None and state.sequence <= self._robot_state.sequence:
                return
            ids = tuple(state.allowed_tag_ids)
            known = {tag.id for tag in self.manifest.profile.field.tags}
            previous = self._selection
            # Invalid processing requests still convey enabled state for the
            # disabled-only mutation lock, but cannot qualify pose publication.
            valid = (
                state.tag_selection_generation > 0
                and ids == tuple(sorted(set(ids)))
                and set(ids) <= known
                and (
                    previous is None
                    or state.tag_selection_generation > previous.generation
                    or (
                        state.tag_selection_generation == previous.generation
                        and ids == previous.allowed_tag_ids
                    )
                )
            )
            self._selection_valid = valid
            if valid:
                self._selection = TagSelection(state.tag_selection_generation, ids)
            self._robot_state = copy.deepcopy(state)
            self._robot_updated = time.monotonic() if now is None else now

    def tag_selection(self, now: float | None = None) -> TagSelection | None:
        """Atomic processing-boundary snapshot; never relaxes mutation eligibility."""
        with self._eligibility_lock:
            now = time.monotonic() if now is None else now
            state = self._robot_state
            if (
                not self.connected
                or not self.fresh
                or state is None
                or self.manifest is None
                or state.robot_session != self.manifest.robot_session
                or not getattr(self, "_selection_valid", False)
                or not 0 <= now - self._robot_updated <= self._state_expiry
            ):
                return None
            return TagSelection(state.tag_selection_generation, tuple(state.allowed_tag_ids))

    def require_eligible(self, now: float | None = None) -> None:
        with self._eligibility_lock:
            now = time.monotonic() if now is None else now
            if self.standalone and not self.connected:
                return
            if (
                self.connected
                and self.fresh
                and self._robot_state is not None
                and not self._robot_state.enabled
                and 0 <= now - self._robot_updated <= self._state_expiry
            ):
                return
            raise ConfigError("Robot enabled or state unknown · locked")

    def begin_standalone(self) -> None:
        with self._eligibility_lock:
            if self.connected:
                raise ConfigError("standalone setup requires a known disconnected robot link")
            self.standalone = True

    def _unbound_device(self, identity: str) -> None:
        if not self._device_exists(identity):
            raise ConfigError("camera is disconnected")
        if self.manifest and any(
            binding["identity"] == identity
            for binding in self.profile_data().get("bindings", {}).values()
        ):
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

    def _commit(
        self,
        data: dict,
        expected: str,
        *,
        code: bool = False,
        manifest: wire.Manifest | None = None,
    ) -> StateSnapshot:
        old_manifest = self.manifest
        target = manifest if manifest is not None else old_manifest
        version = self._connection_version

        def code_eligible() -> None:
            with self._eligibility_lock:
                if not self.connected or version != self._connection_version:
                    raise ConfigError("robot connection changed during profile application")

        snapshot = self.store.commit(
            data,
            expected,
            apply=lambda state: self._apply(state, target),
            rollback=lambda state: self._apply(state, old_manifest),
            eligible=code_eligible if code else self.require_eligible,
        )
        self.state = snapshot
        self.manifest = target
        self.acknowledged_generation = snapshot.generation
        return snapshot

    def accept_manifest(self, manifest: wire.Manifest) -> StateSnapshot:
        validate_manifest(manifest)
        with self._lock:
            if not self.connected:
                raise ConfigError("fresh robot manifest requires current NT connection")
            # A re-sent same profile/session still establishes fresh authority
            # after reconnect. Cached hash equality is never a handshake.
            if self.fresh and self.manifest is not None and manifest == self.manifest:
                return self.state
            target = copy.deepcopy(manifest)
            data = copy.deepcopy(self.state.data)
            profiles = data.setdefault("profiles", {})
            profile = profiles.setdefault(
                target.profile.robot_id, {"bindings": {}, "settings": {}, "modes": {}}
            )
            profile["manifest"] = base64.b64encode(snapshot(target)).decode()
            names = {camera.name for camera in target.profile.cameras}
            # Removed definitions cannot silently bind a later, unrelated role.
            for key in ("bindings", "settings", "modes"):
                profile[key] = {
                    name: value for name, value in profile.get(key, {}).items() if name in names
                }
            data["active_robot"] = target.profile.robot_id
            state = self._commit(data, self.state.generation, code=True, manifest=target)
            self.fresh = True
            self._selection = None
            self._selection_valid = False
            self._robot_state = None
            self._robot_updated = float("-inf")
            return state

    def profile_data(self, data: dict | None = None) -> dict:
        if self.manifest is None:
            raise ConfigError("no robot camera definitions; connect robot code first")
        data = self.state.data if data is None else data
        return data["profiles"][self.manifest.profile.robot_id]

    def camera(self, name: str) -> wire.CameraDefinition:
        if self.manifest is not None:
            for camera in self.manifest.profile.cameras:
                if camera.name == name:
                    return camera
        raise ConfigError("camera name is not configured in robot code")

    def rename(self, identity: str, name: str, expected: str) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            self.camera(name)
            if not self._device_exists(identity):
                raise ConfigError("camera is disconnected; preview-confirm before Rename")
            data = copy.deepcopy(self.state.data)
            bindings = self.profile_data(data).setdefault("bindings", {})
            if name in bindings and bindings[name]["identity"] != identity:
                raise ConfigError("camera name already belongs to another device")
            old = next(
                (key for key, binding in bindings.items() if binding["identity"] == identity), None
            )
            generation = (bindings[old]["generation"] + 1) if old else 1
            if old:
                del bindings[old]
            bindings[name] = {"identity": identity, "generation": generation}
            return self._commit(data, expected)

    def replace_camera(
        self, name: str, expected: str, *, identity: str | None = None
    ) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            data = copy.deepcopy(self.state.data)
            binding = self.profile_data(data).get("bindings", {}).get(name)
            if binding is None:
                raise ConfigError("camera has no physical binding")
            old_identity = binding["identity"]
            identity = identity or old_identity
            if not self._device_exists(identity):
                raise ConfigError("Replacement camera is disconnected; confirm its preview")
            if any(
                key != name and value["identity"] == identity
                for key, value in self.profile_data(data).get("bindings", {}).items()
            ):
                raise ConfigError("Replacement device already has another camera name")
            binding["identity"] = identity
            binding["generation"] += 1
            data["timestamp_qualifications"] = {
                key: value
                for key, value in data.get("timestamp_qualifications", {}).items()
                if key not in {old_identity, identity}
            }
            data["calibrations"] = {
                key: value
                for key, value in data.get("calibrations", {}).items()
                if value["identity"] not in {old_identity, identity}
            }
            return self._commit(data, expected)

    def tune(
        self, name: str, values: dict[str, float], expected: str, *, reset: bool = False
    ) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            camera = self.camera(name)
            policies = {control.name: control for control in camera.controls}
            supported = self._supported_controls(name)
            if reset:
                values = {
                    name: policy.default_value
                    for name, policy in policies.items()
                    if policy.allow_override and (supported is None or name in supported)
                }
            if not values or len(values) > 64:
                raise ConfigError("empty or oversized tuning request")
            for key, value in values.items():
                if supported is not None and key not in supported:
                    raise ConfigError(f"{key}: unavailable on the connected device")
                if key in policies and not policies[key].allow_override:
                    raise ConfigError(f"{key}: pinned or unsupported by robot policy")
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ConfigError(f"{key}: numeric value required")
            data = copy.deepcopy(self.state.data)
            settings = self.profile_data(data).setdefault("settings", {}).setdefault(name, {})
            previous_optical = optical_controls(self.effective_controls(name))
            settings.update(values)
            if optical_controls(self.effective_controls(name, data)) != previous_optical:
                binding = self.profile_data(data).get("bindings", {}).get(name, {})
                data["calibrations"] = {
                    key: record
                    for key, record in data.get("calibrations", {}).items()
                    if record["identity"] != binding.get("identity")
                }
            return self._commit(data, expected)

    def effective_controls(self, name: str, data: dict | None = None) -> dict[str, float]:
        saved = self.profile_data(data).get("settings", {}).get(name, {})
        values = dict(saved)
        values.update(
            {
                policy.name: saved.get(policy.name, policy.default_value)
                if policy.allow_override
                else policy.default_value
                for policy in self.camera(name).controls
            }
        )
        return values

    def set_mode(self, name: str, mode_id: str, expected: str) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            if mode_id not in {mode.id for mode in self.camera(name).allowed_modes}:
                raise ConfigError("mode is not allowed by robot code")
            data = copy.deepcopy(self.state.data)
            self.profile_data(data).setdefault("modes", {})[name] = mode_id
            return self._commit(data, expected)

    def import_data(
        self,
        document: dict,
        expected: str,
        validate: Callable[[dict], None],
        validate_profile: Callable[[dict], None],
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
                "active_robot",
                "profiles",
                "calibrations",
                "calibration_options",
                "timestamp_qualifications",
                "standalone_cameras",
            }:
                raise ConfigError("Unknown imported state fields")
            data = copy.deepcopy(self.state.data)
            robot = self.manifest.profile.robot_id if self.manifest else None
            if incoming.get("active_robot") != robot or robot is None:
                raise ConfigError("Import requires the matching current robot profile")
            profile = incoming.get("profiles", {}).get(robot)
            if not isinstance(profile, dict) or set(profile) - {
                "manifest",
                "bindings",
                "settings",
                "modes",
            }:
                raise ConfigError("Imported robot profile is invalid")
            cached = parse_manifest(base64.b64decode(profile["manifest"], validate=True))
            if cached.manifest_hash != self.manifest.manifest_hash:
                raise ConfigError("Imported code profile hash differs from current robot authority")
            validate_profile(profile)
            current = data["profiles"][robot]
            for key in ("bindings", "settings", "modes"):
                current[key] = copy.deepcopy(profile.get(key, {}))
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
                stored["hash"] = hashlib.sha256(canonical_bytes(record)).hexdigest()
                calibrations[key] = stored
            return self._commit(data, expected)

    def restore(
        self,
        generation: str,
        expected: str,
        validate: Callable[[dict], None],
        identities: list[str] | None = None,
        calibration_hashes: list[str] | None = None,
    ) -> StateSnapshot:
        with self._lock:
            self.require_eligible()
            old = self.store.read_generation(generation)
            # Restore calibration records only; current robot code, bindings and
            # safety policy remain authoritative. Runtime checks optical modes.
            records = {
                key: value
                for key, value in old.data.get("calibrations", {}).items()
                if (identities is None or value["identity"] in identities)
                and (calibration_hashes is None or value.get("hash") in calibration_hashes)
            }
            if not records or (
                identities is not None
                and set(identities) - {r["identity"] for r in records.values()}
            ):
                raise ConfigError("Selected history group is empty or unavailable")
            if calibration_hashes is not None and (
                not calibration_hashes
                or set(calibration_hashes) - {r.get("hash") for r in records.values()}
            ):
                raise ConfigError("Selected calibration records are empty or unavailable")
            for calibration in records.values():
                validate(calibration)
            data = copy.deepcopy(self.state.data)
            data.setdefault("calibrations", {}).update(copy.deepcopy(records))
            return self._commit(data, expected)
