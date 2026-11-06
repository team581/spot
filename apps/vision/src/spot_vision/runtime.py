"""Installed Spot orchestrator: robot authority, one camera owner and shared frames."""

from __future__ import annotations

import copy
import json
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import numpy as np

from . import protocol_models as wire
from .calibration_record import validate_record
from .camera_capture import CameraCapture
from .camera_controls import EXPOSURE_NAMES, frame_limited_exposure
from .clock import FrameRateCounter
from .config import (
    Backend,
    Calibration,
    CameraConfig,
    CameraSelector,
    ConfigError,
    DetectorConfig,
    NtConfig,
    validate_nt_endpoint,
)
from .configuration import ConfigurationService, mode_signature, optical_controls
from .devices import DeviceManager, DeviceRegistry
from .frames import FrameHub
from .health import Watchdog
from .models import DetectedFrame
from .native import create_detector
from .nt_transport import NtTransport, make_observation
from .optical_modes import advertised_modes, mode_supported, preview_mode, preview_modes
from .persistence import StateSnapshot, StateStore, canonical_bytes, durable_replace
from .pose import FieldLayout, FieldTag, PoseSolver, quaternion_to_matrix
from .processing import CameraDetector, ProcessingBudget, ProcessingPolicy, solve_tag_selection
from .runtime_status import StatusSnapshot, build_status
from .system_metrics import SystemMetrics

if TYPE_CHECKING:
    from .calibration import CalibrationManager
    from .networking import NetworkClient


class DebugState(TypedDict):
    samples: list[dict]
    deadline: float
    last: float


def pose_matrix(pose: wire.Pose) -> np.ndarray:
    result = np.eye(4)
    result[:3, :3] = quaternion_to_matrix(np.array([pose.qw, pose.qx, pose.qy, pose.qz]))
    result[:3, 3] = [pose.x_m, pose.y_m, pose.z_m]
    return result


def record_calibration(record: dict, camera: CameraConfig) -> Calibration:
    result = record["intrinsics"]
    calibration = Calibration(
        camera.id,
        result["width"],
        result["height"],
        camera.format,
        tuple(tuple(row) for row in result["camera_matrix"]),
        tuple(result["distortion_coefficients"]),
        result["reprojection_error_px"],
        False,
    )
    calibration.validate_for(camera)
    return calibration


class Runtime:
    def __init__(
        self,
        state_root: Path,
        nt: NtConfig,
        *,
        backend: Backend = "cuda",
        devices: DeviceManager | None = None,
        transport_factory=NtTransport,
        capture_factory=CameraCapture,
        detector_factory=create_detector,
        processing: ProcessingPolicy | None = None,
    ) -> None:
        self.started = time.monotonic()
        self.system_metrics = SystemMetrics()
        self._metrics_updated = 0.0
        self.startup = {
            "state_load_s": None,
            "enumeration_s": None,
            "first_processed_frame_s": None,
            "nt_connection_s": None,
            "synchronized_s": None,
            "configuration_applied_s": None,
        }
        self.backend, self.capture_factory, self.detector_factory = (
            backend,
            capture_factory,
            detector_factory,
        )
        self.devices = devices or DeviceManager(DeviceRegistry(state_root))
        self.store = StateStore(state_root)
        self.nt_settings = state_root / "networktables.json"
        if self.nt_settings.exists():
            saved = validate_nt_endpoint(json.loads(self.nt_settings.read_bytes()))
            nt = replace(nt, team=saved.get("team"), server=saved.get("server"))
        self.nt_config = nt
        self.frames = FrameHub()
        self._pipeline_lock, self._operation_lock = threading.RLock(), threading.RLock()
        self.workers: dict[str, CameraCapture] = {}
        self.detectors: dict[str, CameraDetector] = {}
        self.solvers: dict[str, PoseSolver] = {}
        self.roles: dict[str, str] = {}
        self.modes: dict[str, wire.OpticalMode] = {}
        self.calibrations: dict[str, dict] = {}
        self.generation, self.faults = "", {}
        self._preview_failed = {}
        self.processing = processing or ProcessingPolicy()
        self.processing_budget = ProcessingBudget(self.processing)
        self.configuration = ConfigurationService(
            self.store,
            self.apply,
            device_exists=lambda identity: self.devices.get(identity) is not None,
            supported_controls=self._supported_controls,
        )
        self.startup["state_load_s"] = time.monotonic() - self.started
        self.transport = transport_factory(nt, self.configuration, self.camera_ready)
        self.stop_event = threading.Event()
        self.commands: queue.Queue = queue.Queue(maxsize=16)
        self.progress = {
            "configuration": time.monotonic(),
            "detector": time.monotonic(),
            "discovery": time.monotonic(),
        }
        self.threads = [
            threading.Thread(target=method, name=name, daemon=True)
            for name, method in (
                ("configuration", self._configure),
                ("detector", self._detect),
                ("discovery", self._discover),
            )
        ]
        self.watchdog = Watchdog()
        self.fatal = ""
        self.software = {}
        self.debug: DebugState = {"samples": [], "deadline": 0.0, "last": 0.0}
        self.calibration: CalibrationManager | None = (
            None  # attached by installed application before starting
        )
        self.network: NetworkClient | None = None
        self.endpoint: dict = {"configured": nt.server, "team": nt.team, "mode": "NT4 client"}

    def submit(self, operation: str, payload: dict) -> Future:
        future = Future()
        if operation.startswith("network/"):
            if self.network is None:
                future.set_exception(ConfigError("Network helper is not installed"))
                return future
            return self.network.submit(operation.split("/", 1)[1], payload)
        try:
            self.commands.put_nowait((operation, copy.deepcopy(payload), future))
        except queue.Full:
            future.set_exception(
                ConfigError("Configuration queue busy; retry after pending request")
            )
        return future

    def _configure(self) -> None:
        while not self.stop_event.is_set():
            self.progress["configuration"] = time.monotonic()
            try:
                with self._operation_lock:
                    self.transport.poll()
                    self.transport.configuration_applied()
                    self._debug_tick()
                operation, payload, future = self.commands.get(timeout=0.05)
            except queue.Empty:
                continue
            except Exception as exc:  # noqa: BLE001 - isolate backend/job failures at the worker boundary
                self.faults["configuration"] = str(exc)
                continue
            try:
                with self._operation_lock:
                    if operation == "nt/endpoint":
                        result = self.set_nt_endpoint(payload)
                    elif operation == "rediscover":
                        self.apply(self.configuration.state, self.configuration.manifest)
                        result = self.configuration.state
                    elif operation == "configuration/clear-overrides":
                        result = self.configuration.clear_overrides(
                            payload["revision"], payload.get("path", "")
                        )
                    elif operation == "configuration/apply":
                        result = self.configuration.configure_document(
                            payload["document"], payload["revision"]
                        )
                    elif operation == "configuration/import":
                        result = self.configuration.import_data(
                            payload["document"],
                            payload["revision"],
                            validate_record,
                        )
                    elif operation == "debug/record":
                        if payload["revision"] != self.configuration.state.generation:
                            raise ConfigError("revision conflict; fetch current configuration")
                        seconds = payload.get("seconds", 10)
                        if type(seconds) is not int or not 1 <= seconds <= 30:
                            raise ConfigError("Debug recording is bounded to 1–30 seconds")
                        self.debug = {
                            "samples": [],
                            "deadline": time.monotonic() + seconds,
                            "last": 0.0,
                        }
                        result = {"recording": True, "seconds": seconds}
                    elif operation == "device/name":
                        result = self.configuration.rename(
                            payload["identity"], payload["name"], payload["revision"]
                        )
                    elif operation == "camera/tune":
                        identity = next(
                            (key for key, name in self.roles.items() if name == payload["name"]),
                            None,
                        )
                        self._validate_exposure(identity, payload.get("values", {}))
                        result = self.configuration.tune(
                            payload["name"],
                            payload.get("values", {}),
                            payload["revision"],
                            reset=payload.get("reset", False),
                        )
                    elif operation == "camera/mode":
                        camera = self.configuration.camera(payload["name"])
                        device = self.devices.get(camera.binding_id) if camera.binding_id else None
                        mode = next(
                            (
                                m
                                for m in [
                                    *camera.allowed_modes,
                                    *(advertised_modes(device) if device else []),
                                ]
                                if m.id == payload["mode_id"]
                            ),
                            None,
                        )
                        if mode is None or device is None or not mode_supported(device, mode):
                            raise ConfigError(
                                "Selected optical mode is not advertised by the connected device"
                            )
                        result = self.configuration.set_mode(camera.name, mode, payload["revision"])
                    elif operation == "camera/replace":
                        identity = payload.get("identity")
                        worker = self.workers.get(identity) if identity else None
                        if identity and (not worker or not worker.verified):
                            raise ConfigError("Replacement camera requires a verified preview")
                        result = self.configuration.replace_camera(
                            payload["name"], payload["revision"], identity=payload.get("identity")
                        )
                    elif operation == "configuration/restore":
                        result = self.configuration.restore(
                            payload["generation"],
                            payload["revision"],
                            self.validate_calibration,
                            identities=payload.get("identities"),
                            calibration_ids=payload.get("calibration_ids"),
                        )
                    elif operation.startswith("calibration/") and self.calibration is not None:
                        result = self.calibration.command(operation.split("/", 1)[1], payload)
                    else:
                        raise ConfigError("Unknown configuration operation")
                    self.transport.configuration_applied()
                future.set_result(
                    {
                        "revision": self.configuration.state.generation,
                        "applied_generation": self.configuration.applied_generation,
                        "result": result if isinstance(result, dict) else None,
                        "controls": dict(self.workers[payload["identity"]].readback)
                        if operation.startswith("device/")
                        and payload.get("identity") in self.workers
                        else self._readback_for_name(payload.get("name")),
                    }
                )
                self.faults.pop("configuration", None)
            except Exception as exc:  # noqa: BLE001 - isolate backend/job failures at the worker boundary
                future.set_exception(exc)

    def set_nt_endpoint(self, endpoint: dict) -> dict:
        endpoint = validate_nt_endpoint(endpoint)
        team, server = endpoint.get("team"), endpoint.get("server")
        with self._pipeline_lock:
            previous = self.nt_config
            updated = replace(previous, team=team, server=server)
            try:
                self.transport.set_endpoint(updated)
                durable_replace(self.nt_settings, canonical_bytes(endpoint))
            except Exception:
                self.transport.set_endpoint(previous)
                raise
            self.nt_config = updated
            self.endpoint.update(configured=server, team=team)
        return endpoint

    def _discover(self) -> None:
        previous = None
        while not self.stop_event.is_set():
            self.progress["discovery"] = time.monotonic()
            self.devices.refresh()
            self.startup["enumeration_s"] = (
                self.startup["enumeration_s"] or time.monotonic() - self.started
            )
            snapshot = self.devices.snapshot()[:32]
            key: list[tuple] = [(d["identity"], d["capture_node"], d["fault"]) for d in snapshot]
            # A bounded advertised preview probe advances only after its owner
            # actually fails; healthy cameras never get reopened by discovery.
            key += [
                (identity, worker.counters.capture_failures)
                for identity, worker in list(self.workers.items())
                if identity not in self.roles
                and not worker.verified
                and worker.counters.captured == 0
            ]
            if key != previous:
                self.submit("rediscover", {})
                previous = key
            # Enumeration is off the HTTP/startup path and retries without any
            # dependency on network-online or on the robot boot order.
            self.stop_event.wait(1)

    def _camera_config(self, identity, mode, definition) -> CameraConfig:
        device = self.devices.get(identity)
        if device is None:
            raise ConfigError("Camera is no longer connected")
        return CameraConfig(
            identity,
            True,
            CameraSelector(device=device.capture_node),
            mode.pixel_format,
            mode.width,
            mode.height,
            round(mode.fps),
            None,
            0,
            definition.detector if definition else DetectorConfig(backend=self.backend),
            image_rotation_deg=definition.image_rotation_deg if definition else 0,
        )

    def apply(self, state: StateSnapshot, manifest: wire.Manifest | None) -> None:
        """Switch at a scheduler boundary, retaining capture workers for tuning."""
        self.transport.invalidate_configuration()
        bindings = (
            {c.name: {"identity": c.binding_id} for c in manifest.profile.cameras if c.binding_id}
            if manifest
            else {}
        )
        processing = manifest.profile.processing if manifest else self.processing
        definitions = {c.name: c for c in manifest.profile.cameras} if manifest else {}
        roles = {b["identity"]: name for name, b in bindings.items() if name in definitions}
        layout = (
            FieldLayout(
                {
                    t.id: FieldTag(t.id, pose_matrix(t.field_to_tag))
                    for t in manifest.profile.field.tags
                },
                0,
            )
            if manifest
            else None
        )
        desired, modes, calibration_records, faults, controls = {}, {}, {}, {}, {}
        for device in self.devices.snapshot()[:32]:
            identity = device["identity"]
            physical = self.devices.get(identity)
            name = roles.get(identity)
            definition = definitions.get(name)
            if definition and not definition.enabled:
                continue
            if physical is None:
                raise ConfigError("Camera is no longer connected")
            if not physical.capture_node or physical.fault:
                faults[identity] = physical.fault or "No capture node"
                continue
            if definition:
                mode = definition.allowed_modes[0]
                if mode is None or not mode_supported(physical, mode):
                    faults[identity] = "Code optical mode is not advertised by this device"
                    continue
                available = {c["name"] for c in physical.controls}
                missing_required = [
                    c.name for c in definition.controls if c.required and c.name not in available
                ]
                if missing_required:
                    faults[identity] = "Required controls unavailable: " + ", ".join(
                        missing_required
                    )
                    continue
                controls[identity] = {
                    c.name: c.default_value for c in definition.controls if c.name in available
                }
            else:
                # Probe only bounded advertised modes. Never infer a logical
                # camera name, optical signature or production calibration.
                # High-speed UVC devices may advertise only 120/210 FPS. Use
                # their actual cadence within a pixel-rate budget; processing
                # and browser previews retain their separate rate limits.
                candidates = preview_modes(physical)
                failed = self._preview_failed.setdefault(identity, set())
                previous = self.workers.get(identity)
                if (
                    previous
                    and not previous.verified
                    and previous.counters.captured == 0
                    and previous.counters.capture_failures
                ):
                    failed.add(
                        (
                            previous.camera.width,
                            previous.camera.height,
                            previous.camera.format,
                            previous.camera.fps,
                        )
                    )
                untried = [
                    m
                    for m in candidates
                    if (m["width"], m["height"], m["pixel_format"], round(m["fps"])) not in failed
                ]
                if not untried and previous:
                    # Exhausted candidates retain one bounded recovering owner.
                    untried = [
                        m
                        for m in candidates
                        if (m["width"], m["height"], m["pixel_format"], round(m["fps"]))
                        == (
                            previous.camera.width,
                            previous.camera.height,
                            previous.camera.format,
                            previous.camera.fps,
                        )
                    ]
                selected = min(
                    untried,
                    key=lambda m: (
                        m["fps"] > 30,
                        abs(m["width"] - 640) + abs(m["height"] - 480),
                        abs(m["fps"] - 30),
                    ),
                    default=None,
                )
                if selected is None:
                    faults[identity] = "No bounded supported preview mode advertised"
                    continue
                mode = preview_mode(selected)
                controls[identity] = {}
            modes[identity] = mode
            desired[identity] = self._camera_config(identity, mode, definition)
            record = definition.calibration if definition else None
            if (
                record
                and record["mode_signature"] == mode_signature(mode)
                and record["identity"] == identity
                and record.get("image_rotation_deg", 0) == desired[identity].image_rotation_deg
                and record.get("optical_controls", {}) == optical_controls(controls[identity])
            ):
                calibration_records[identity] = record
        # Cap aggregate raw/native image storage before any allocation. This
        # is a safety ceiling, not a qualified Jetson camera-count budget.
        pixels = 0
        for identity, camera in list(desired.items()):
            pixels += camera.width * camera.height
            if pixels > 16_777_216:
                faults[identity] = "Aggregate image resource budget exceeded"
                del desired[identity]
                calibration_records.pop(identity, None)
        self.frames.retain(set(desired) | set(roles))
        # All selected calibration records are checked before any device write.
        prepared, solvers = {}, {}
        previous_field = getattr(self, "_field", None)
        field = manifest.profile.field if manifest else None
        with self._pipeline_lock:
            for identity, camera in desired.items():
                if identity in calibration_records:
                    validate_record(calibration_records[identity])
                calibration = (
                    record_calibration(calibration_records[identity], camera)
                    if identity in calibration_records
                    else None
                )
                try:
                    old = self.calibrations.get(identity)
                    unchanged = (
                        self.processing == processing
                        and identity in self.detectors
                        and identity in self.workers
                        and self.workers[identity].camera == camera
                        and old == calibration_records.get(identity)
                    )
                    prepared[identity] = (
                        self.detectors[identity]
                        if unchanged
                        else CameraDetector(camera, calibration, self.detector_factory)
                    )
                    solvers[identity] = (
                        self.solvers[identity]
                        if unchanged and previous_field == field
                        else PoseSolver(
                            calibration,
                            layout,
                            0.1651,
                            tag_sizes={t.id: t.size_m for t in manifest.profile.field.tags}
                            if manifest
                            else {},
                        )
                    )
                except Exception as exc:
                    if identity in calibration_records:
                        raise ConfigError(f"Calibration detector rebuild failed: {exc}") from exc
                    faults[identity] = f"Detector unavailable: {exc}"
            for identity, worker in list(self.workers.items()):
                camera = desired.get(identity)
                if camera is None or camera != worker.camera:
                    worker.stop()  # must finish before creating another owner
                    del self.workers[identity]
            started_workers = []
            for identity, camera in desired.items():
                if hasattr(self, "progress"):
                    self.progress["configuration"] = time.monotonic()
                worker = self.workers.get(identity)
                if worker:
                    if worker.verified:
                        worker.update(
                            state.generation, controls[identity], reset_defaults=identity in roles
                        )
                    else:
                        # Recovery uses the existing authorized profile; it does
                        # not unlock GUI edits or acknowledge a failed tuning.
                        if controls[identity] != worker.requested or worker.reset_defaults != (
                            identity in roles
                        ):
                            raise ConfigError(
                                "Cannot acknowledge settings for an unavailable camera"
                            )
                        worker.generation = state.generation
                else:
                    physical = self.devices.get(identity)
                    if physical is None or physical.capture_node is None:
                        raise ConfigError("Camera capture node is no longer available")
                    worker = self.capture_factory(
                        camera,
                        physical.capture_node,
                        state.generation,
                        controls[identity],
                        self.frames.capture,
                        reset_defaults=identity in roles,
                    )
                    self.workers[identity] = worker
                    worker.start()
                    started_workers.append((identity, worker))
            deadline = time.monotonic() + 3
            for identity, worker in started_workers:
                worker.ready.wait(max(0, deadline - time.monotonic()))
                if not worker.verified:
                    faults[identity] = worker.counters.error or "Camera initialization pending"
                    if identity in roles:
                        raise ConfigError(
                            f"Camera settings verification failed: {faults[identity]}"
                        )
            correction = -round(manifest.profile.latency_ms * 1000) if manifest else 0
            for worker in self.workers.values():
                with worker._lock:
                    worker.timestamp_correction_us = correction
            self._field = field
            self.processing = processing
            self.processing_budget.policy = processing
            self.detectors, self.solvers, self.roles = prepared, solvers, roles
            self.modes, self.calibrations, self.generation = (
                modes,
                calibration_records,
                state.generation,
            )
            self.faults = {
                **{k: v for k, v in self.faults.items() if k in {"configuration"}},
                **faults,
            }

    def _detect(self) -> None:
        rates, cursor = {}, 0
        while not self.stop_event.wait(0.001):
            self.progress["detector"] = time.monotonic()
            with self._pipeline_lock:
                identities = sorted(self.detectors)
                if not identities:
                    continue
                identity = identities[cursor % len(identities)]
                cursor += 1
                now = time.monotonic()
                self.processing_budget.update(self.detectors)
                detector = self.detectors[identity]
                if not self.processing_budget.due(identity, now) or not detector.ready(now):
                    continue
                worker = self.workers.get(identity)
                frame = worker.slot.take() if worker else None
                if worker is None or frame is None or frame.runtime_generation != self.generation:
                    continue
                try:
                    batch = self.detectors[identity].detect(frame.image)
                    detected = DetectedFrame(
                        frame, batch, (time.monotonic_ns() - frame.captured_monotonic_ns) / 1e6
                    )
                    selection = self.configuration.tag_selection()
                    # Detect once. Retain every detection for diagnostics while
                    # solving only the selected rays; never relabel a broad solve.
                    solution = solve_tag_selection(
                        self.solvers[identity], batch.detections, selection
                    )
                    worker.counters.detected += 1
                    worker.counters.last_detection_monotonic = time.monotonic()
                    worker.counters.fps_detect = rates.setdefault(
                        identity, FrameRateCounter()
                    ).update(time.monotonic())
                    self.frames.result(detected, solution)
                    if self.faults.get(identity, "").startswith("Processing failed:"):
                        self.faults.pop(identity, None)
                    self.startup["first_processed_frame_s"] = (
                        self.startup["first_processed_frame_s"] or time.monotonic() - self.started
                    )
                    name = self.roles.get(identity)
                    if name and not self.devices.registry.fault:
                        context = self.transport.context(name, frame.captured_monotonic_ns)
                        if context and context.generation == frame.runtime_generation:
                            published = self.transport.publish(
                                make_observation(
                                    detected,
                                    solution,
                                    context,
                                    (time.monotonic_ns() - frame.captured_monotonic_ns) / 1e6,
                                    selection=selection,
                                ),
                                frame.captured_monotonic_ns,
                            )
                            if published:
                                worker.counters.published += 1
                                worker.counters.last_publish_monotonic = time.monotonic()
                            else:
                                worker.counters.withheld += 1
                        else:
                            worker.counters.withheld += 1
                except Exception as exc:  # noqa: BLE001 - isolate backend/job failures at the worker boundary
                    self.faults[identity] = f"Processing failed: {exc}"
                finally:
                    self.processing_budget.completed(identity, now, time.monotonic() - now)

    def camera_ready(self, name: str) -> bool:
        identity = self.configuration.camera(name).binding_id
        worker = self.workers.get(identity)
        return bool(
            self.calibrations.get(identity)
            and worker
            and worker.verified
            and identity in self.detectors
            and not self.devices.registry.fault
        )

    def _readback_for_name(self, name) -> dict:
        identity = next(
            (identity for identity, camera_name in self.roles.items() if camera_name == name), None
        )
        worker = self.workers.get(identity)
        return dict(worker.readback) if worker else {}

    def _debug_tick(self) -> None:
        now = time.monotonic()
        if not self.debug["deadline"]:
            return
        if now - self.debug["last"] >= 1 and now <= self.debug["deadline"]:
            self.debug["last"] = now
            self.debug["samples"].append(
                {
                    "uptime_s": now - self.started,
                    "generation": self.generation,
                    "cameras": {
                        identity: worker.counters.snapshot()
                        for identity, worker in self.workers.items()
                    },
                    "clock": asdict(self.transport.clock.snapshot()),
                }
            )
        if now > self.debug["deadline"]:
            durable_replace(self.store.root / "debug-latest.json", canonical_bytes(self.debug))
            self.debug["deadline"] = 0.0

    def validate_calibration(self, record: dict) -> None:
        if (
            not isinstance(record, dict)
            or not record.get("identity")
            or not record.get("mode_signature")
        ):
            raise ConfigError("Invalid physical calibration metadata")
        validate_record(record)
        identity = record["identity"]
        mode = self.modes.get(identity)
        if mode is None or record["mode_signature"] != mode_signature(mode):
            raise ConfigError("Calibration does not match the current physical optical mode")
        worker = self.workers.get(identity)
        if worker is None or not worker.verified:
            raise ConfigError("Calibration camera is unavailable")
        if record.get("image_rotation_deg", 0) != worker.camera.image_rotation_deg:
            raise ConfigError("Calibration image orientation mismatch")
        if not record.get("holdout", {}).get("accepted") or not record.get("fit", {}).get(
            "accepted"
        ):
            raise ConfigError("Calibration fit and separate validation must both pass")
        if record.get("optical_controls", {}) != optical_controls(worker.readback):
            raise ConfigError("Calibration lens/control state mismatch")
        record_calibration(record, worker.camera)

    def _validate_exposure(self, identity, values):
        device, mode = self.devices.get(identity), self.modes.get(identity)
        if not device or mode is None:
            return
        for control in device.controls:
            name = control["name"]
            if name not in EXPOSURE_NAMES or name not in values:
                continue
            limited = frame_limited_exposure(
                {
                    **control,
                    **{key: control[key] * control["factor"] for key in ("min", "max", "step")},
                },
                mode.fps,
            )
            value = values[name]
            if not limited["exposure_limit_available"] or (
                type(value) in (int, float) and value > limited["max"]
            ):
                raise ConfigError(
                    f"Exposure must fit one {mode.fps:g} FPS frame (maximum {limited['max']:g} µs)"
                )

    def _supported_controls(self, name):
        device = self.devices.get(name)
        if device:
            return {control["name"] for control in device.controls}
        camera = self.configuration.camera(name)
        device = self.devices.get(camera.binding_id)
        return {control["name"] for control in device.controls} if device else set()

    def processing_faults(self) -> list[str]:
        if self.processing_budget.overloaded:
            return ["Processing overload · reduced cadence"]
        return []

    def status(self) -> StatusSnapshot:
        return build_status(self)

    def start(self) -> None:
        self.frames.start()
        if self.calibration:
            self.calibration.start()
        for thread in self.threads:
            thread.start()

    def tick(self) -> bool:
        now = time.monotonic()
        if now - self._metrics_updated >= 1:
            self.system_metrics.update()
            self._metrics_updated = now
        stalled = [
            t.name
            for t in self.threads
            if not t.is_alive()
            or now
            - (
                max(self.progress[t.name], getattr(self.devices, "last_progress", 0))
                if t.name == "discovery"
                else self.progress[t.name]
            )
            > 12
        ]
        # apply() stops/removes old owners and registers/starts new ones under
        # this lock. Do not mistake either transition for a dead capture worker,
        # or block the watchdog while hardware configuration is in progress.
        if self._pipeline_lock.acquire(blocking=False):
            try:
                stalled += [
                    w.name
                    for w in list(self.workers.values())
                    if not w.is_alive() or now - w.last_progress > 6
                ]
            finally:
                self._pipeline_lock.release()
        if self.frames.worker.is_alive() and now - self.frames.last_progress > 6:
            stalled.append("preview-encoder")
        if not self.frames.worker.is_alive():
            stalled.append("preview-encoder")
        if self.calibration and (
            not self.calibration.capture_worker.is_alive()
            or not self.calibration.solve_worker.is_alive()
            or now - self.calibration.last_progress > 12
            or (
                self.calibration.active_job_started is not None
                and now - self.calibration.active_job_started > 90
            )
        ):
            stalled.append("calibration")
        if stalled:
            self.fatal = "Workers stalled: " + ", ".join(stalled)
            return False
        self.transport.heartbeat()
        sync = self.transport.clock.snapshot()
        for key, active in (
            ("nt_connection_s", self.configuration.connected),
            ("synchronized_s", sync.state == "Synchronized"),
            ("configuration_applied_s", bool(self.configuration.applied_generation)),
        ):
            if active and self.startup[key] is None:
                self.startup[key] = now - self.started
        self.watchdog.ping("Spot · " + (self.fatal or sync.state))
        return True

    def close(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=4)
        for worker in list(self.workers.values()):
            worker.stop()
        if self.calibration:
            self.calibration.close()
        self.frames.close()
        self.transport.close()
        self.watchdog.stopping()
