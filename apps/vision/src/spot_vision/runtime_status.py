"""Read-only operator snapshots, separate from camera ownership and scheduling."""

from __future__ import annotations

import copy
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, TypedDict

from .camera_controls import frame_limited_exposure
from .config import ConfigError
from .configuration import mode_signature
from .optical_modes import mode_supported, preview_mode, preview_modes
from .timing_qualification import timing_signature

if TYPE_CHECKING:
    from .beta_runtime import BetaRuntime


class StatusSnapshot(TypedDict):
    revision: str
    applied_generation: str
    cameras: list[dict]
    names: list[str]
    robot_id: str | None
    fresh: bool
    lock_reason: str
    standalone: bool
    connected: bool
    clock: dict
    faults: list[str]
    uptime_s: float
    system: dict
    robot_decisions: dict
    startup: dict
    software: dict
    calibration: dict
    history: list[dict]
    network: dict
    endpoint: dict
    field: dict | None


def camera_health(
    *,
    enabled: bool,
    assigned: bool,
    connected: bool,
    fault: str,
    configuration_mismatch: bool,
    calibrated: bool,
    detect_age: float | None,
    no_tags: bool,
) -> str:
    if not enabled:
        return "Disabled"
    if not assigned:
        return "Unassigned"
    if configuration_mismatch:
        return "Configuration mismatch"
    if not connected or fault:
        return "Recovering"
    if not calibrated:
        return "Calibration needed"
    if detect_age is None or detect_age > 0.5:
        return "Recovering"
    return "No tags" if no_tags else "Ready"


def build_status(runtime: BetaRuntime) -> StatusSnapshot:
    config = runtime.configuration
    try:
        config.require_eligible()
        lock_reason = ""
    except ConfigError as exc:
        lock_reason = str(exc)
    devices = runtime.devices.snapshot()[:32]
    manifest = config.manifest
    definitions = list(manifest.profile.cameras) if manifest else []
    bindings = config.profile_data().get("bindings", {}) if manifest else {}
    by_identity = {b["identity"]: name for name, b in bindings.items()}
    cameras = []
    for device in devices:
        identity = device["identity"]
        name = by_identity.get(identity)
        definition = next((c for c in definitions if c.name == name), None)
        standalone_setup = not name and identity in config.state.data.get("standalone_cameras", {})
        worker = runtime.workers.get(identity)
        record = runtime.calibrations.get(identity)
        capabilities = []
        actual_capabilities = getattr(worker, "capabilities", None) if worker else None
        for control in (
            actual_capabilities if actual_capabilities is not None else device["controls"]
        ):
            policy = (
                next((c for c in definition.controls if c.name == control["name"]), None)
                if definition
                else None
            )
            factor = control["factor"]
            capabilities.append(
                {
                    **control,
                    "min": control["min"] * factor,
                    "max": control["max"] * factor,
                    "step": control["step"] * factor,
                    "value": worker.readback.get(control["name"], control["value"] * factor)
                    if worker
                    else control["value"] * factor,
                    "allowed": bool(
                        control["writable"]
                        and (
                            (definition is not None and (policy is None or policy.allow_override))
                            or standalone_setup
                        )
                    ),
                    "default": policy.default_value if policy else None,
                    "required": bool(policy and policy.required),
                    "reason": ""
                    if (definition is not None and (policy is None or policy.allow_override))
                    or standalone_setup
                    else "Pinned by robot code"
                    if policy
                    else "Not allowed by robot code",
                }
            )
            if identity in runtime.modes:
                capabilities[-1] = frame_limited_exposure(
                    capabilities[-1],
                    runtime.modes[identity].fps,
                )
        camera = {
            **device,
            "name": name or device["display_id"],
            "logical_name": name,
            "standalone_setup": standalone_setup,
            "required": bool(definition and definition.required),
            "timing_signature": timing_signature(runtime.modes[identity], worker.readback)
            if worker and identity in runtime.modes
            else None,
            "timestamp_qualified": bool(
                worker and getattr(worker, "timestamp_uncertainty_s", None)
            ),
            "present": True,
            "connected": bool(worker and worker.verified),
            "controls": capabilities,
            "calibrated": bool(record),
            "calibration_hash": record.get("hash", "") if record else "",
            "warning": "Choose a code-defined name"
            if not name
            else "Calibration required"
            if not record
            else "",
            "fault": (
                runtime.faults.get(identity, "")
                if runtime.faults.get(identity, "").startswith(("Processing", "Detector"))
                else worker.counters.error
                if worker
                else runtime.faults.get(identity, device["fault"])
            ),
            "metrics": {
                **worker.counters.snapshot(),
                "publish_age_s": time.monotonic() - worker.counters.last_publish_monotonic
                if worker.counters.last_publish_monotonic
                else None,
                "detect_age_s": time.monotonic() - worker.counters.last_detection_monotonic
                if worker.counters.last_detection_monotonic
                else None,
            }
            if worker
            else {},
            "processing": {
                **runtime.detectors[identity].snapshot(),
                "target_fps": runtime.processing_budget.targets.get(identity),
                "thermal_reduction": runtime.processing_budget.thermal,
                "overload_reduction": runtime.processing_budget.overloaded,
            }
            if identity in runtime.detectors
            else {},
            "age_s": None
            if worker is None or worker.frame is None
            else (time.monotonic_ns() - worker.frame.captured_monotonic_ns) / 1e9,
            "mode_id": (
                mode_signature(runtime.modes[identity]) if not name else runtime.modes[identity].id
            )
            if identity in runtime.modes
            else None,
            "mode_signature": mode_signature(runtime.modes[identity])
            if identity in runtime.modes
            else None,
            "allowed_modes": [
                {
                    "id": m.id,
                    "width": m.width,
                    "height": m.height,
                    "fps": m.fps,
                    "pixel_format": m.pixel_format,
                    "supported": mode_supported(runtime.devices.get(identity), m),
                }
                for m in definition.allowed_modes
            ]
            if definition
            else [
                {"id": mode_signature(preview_mode(m)), **m, "supported": True}
                for m in preview_modes(runtime.devices.get(identity))
            ],
            "geometry": {
                "translation": [
                    definition.robot_to_camera.x_m,
                    definition.robot_to_camera.y_m,
                    definition.robot_to_camera.z_m,
                ],
                "quaternion": [
                    definition.robot_to_camera.qw,
                    definition.robot_to_camera.qx,
                    definition.robot_to_camera.qy,
                    definition.robot_to_camera.qz,
                ],
            }
            if definition
            else {"translation": [0, 0, 0], "quaternion": [1, 0, 0, 0], "placeholder": True}
            if standalone_setup
            else None,
        }
        processed = runtime.frames.results.get(identity)
        if processed and worker:
            detected = processed[0]
            camera["metrics"].update(
                {
                    "processed_sequence": detected.frame.sequence,
                    "processed_capture_epoch": detected.frame.capture_epoch,
                    "detect_ms": detected.batch.detect_ms,
                    "capture_to_detect_ms": detected.capture_to_detect_ms,
                    "tag_ids": [tag.id for tag in detected.batch.detections],
                }
            )
        camera["health"] = camera_health(
            enabled=definition.enabled if definition else True,
            assigned=bool(name),
            connected=camera["connected"],
            fault=camera["fault"],
            configuration_mismatch=not worker and bool(runtime.faults.get(identity)),
            calibrated=bool(record),
            detect_age=camera["metrics"].get("detect_age_s"),
            no_tags=bool(processed and not processed[0].batch.detections),
        )
        cameras.append(camera)
    for definition in definitions:
        binding = bindings.get(definition.name, {})
        if binding.get("identity") not in {d["identity"] for d in devices}:
            missing_identity = binding.get("identity")
            last_frame = runtime.frames.image(missing_identity)
            selected = config.profile_data().get("modes", {}).get(definition.name)
            mode = next(
                (m for m in definition.allowed_modes if m.id == selected),
                next(iter(definition.allowed_modes), None),
            )
            record = (
                config.state.data.get("calibrations", {}).get(
                    missing_identity + ":" + mode_signature(mode)
                )
                if missing_identity and mode
                else None
            )
            cameras.append(
                {
                    "identity": binding.get("identity", "missing:" + definition.name),
                    "name": definition.name,
                    "logical_name": definition.name,
                    "required": definition.required,
                    "health": "Missing" if definition.enabled else "Disabled",
                    "timestamp_qualified": False,
                    "present": False,
                    "connected": False,
                    "calibrated": bool(record),
                    "calibration_hash": record.get("hash", "") if record else "",
                    "warning": "Configured camera missing",
                    "fault": "Disconnected",
                    "controls": [],
                    "metrics": {},
                    "age_s": (time.monotonic_ns() - last_frame.captured_monotonic_ns) / 1e9
                    if last_frame
                    else None,
                    "geometry": {
                        "translation": [
                            definition.robot_to_camera.x_m,
                            definition.robot_to_camera.y_m,
                            definition.robot_to_camera.z_m,
                        ],
                        "quaternion": [
                            definition.robot_to_camera.qw,
                            definition.robot_to_camera.qx,
                            definition.robot_to_camera.qy,
                            definition.robot_to_camera.qz,
                        ],
                    },
                }
            )
    sync = runtime.transport.clock.snapshot()
    return {
        "revision": config.state.generation,
        "applied_generation": config.acknowledged_generation,
        "cameras": cameras,
        "names": [c.name for c in definitions],
        "robot_id": manifest.profile.robot_id if manifest else None,
        "fresh": config.fresh,
        "lock_reason": lock_reason,
        "standalone": config.standalone,
        "connected": config.connected,
        "clock": asdict(sync),
        "faults": list(runtime.faults.values())
        + runtime.processing_faults()
        + ([runtime.devices.fault] if runtime.devices.fault else [])
        + ([runtime.store.fault] if runtime.store.fault else []),
        "uptime_s": time.monotonic() - runtime.started,
        "system": runtime.system_metrics.snapshot.copy(),
        "robot_decisions": getattr(runtime.transport, "robot_decisions", {}),
        "startup": runtime.startup.copy(),
        "software": runtime.software,
        "calibration": runtime.calibration.status() if runtime.calibration else {},
        "history": runtime.store.history(),
        "network": copy.deepcopy(runtime.network.snapshot)
        if runtime.network
        else {"available": False},
        "endpoint": {
            **getattr(runtime, "endpoint", {}),
            **(
                {"local_addresses": runtime.network.snapshot.get("local_addresses", [])}
                if runtime.network and runtime.network.snapshot.get("available")
                else {}
            ),
        },
        "field": {
            "length": manifest.profile.field.length_m,
            "width": manifest.profile.field.width_m,
            "tags": [
                {
                    "id": tag.id,
                    "size": tag.size_m,
                    "translation": [
                        tag.field_to_tag.x_m,
                        tag.field_to_tag.y_m,
                        tag.field_to_tag.z_m,
                    ],
                    "quaternion": [
                        tag.field_to_tag.qw,
                        tag.field_to_tag.qx,
                        tag.field_to_tag.qy,
                        tag.field_to_tag.qz,
                    ],
                }
                for tag in manifest.profile.field.tags
            ],
        }
        if manifest
        else None,
    }
