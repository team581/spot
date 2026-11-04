"""NT4 v2 boundary: coherent acknowledgements and no offline backlog replay."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .beta_contract import MAX_TAGS, content_hash, parse_manifest, validate_observation
from .clock import ClockGate, nt_now_us
from .config import ConfigError, NtConfig
from .configuration import ConfigurationService, TagSelection
from .models import DetectedFrame, PoseSolution
from .proto import vision_v2_pb2 as wire

LOGGER = logging.getLogger(__name__)
ROOT = "/Spot/v2"


@dataclass(frozen=True)
class ObservationContext:
    acknowledgement: wire.Acknowledgement
    camera: wire.CameraGeneration
    applied_monotonic_ns: int
    timestamp_uncertainty_s: float | None


def make_observation(
    detected: DetectedFrame,
    solution: PoseSolution,
    context: ObservationContext,
    total_ms: float,
    *,
    selection: TagSelection | None = None,
) -> wire.Observation:
    ack, camera, frame = context.acknowledgement, context.camera, detected.frame
    message = wire.Observation(
        schema_version=2,
        tag_selection_generation=selection.generation if selection else 0,
        robot_id=ack.robot_id,
        robot_session=ack.robot_session,
        service_session=ack.service_session,
        capture_epoch=frame.capture_epoch,
        connection_epoch=ack.connection_epoch,
        sync_epoch=ack.sync_epoch,
        sequence=frame.sequence,
        camera_name=camera.camera_name,
        binding_id=camera.binding_id,
        binding_generation=camera.binding_generation,
        manifest_hash=ack.manifest_hash,
        field_hash=ack.field_hash,
        calibration_hash=camera.calibration_hash,
        calibration_valid=camera.calibration_valid,
        runtime_generation=ack.runtime_generation,
        mode_id=camera.mode_id,
        optical_signature=camera.optical_signature,
        capture_local_nt_us=frame.capture_timestamp_us,
        timestamp_source=frame.timestamp_source,
        timestamp_uncertainty_s=context.timestamp_uncertainty_s or 0,
    )
    detections = detected.batch.detections[:MAX_TAGS]
    by_id = {tag.id: tag for tag in detections}
    h, w = frame.image.shape[:2]
    if camera.calibration_valid and context.timestamp_uncertainty_s is not None:
        for candidate in solution.candidates[:2]:
            pose = wire.Pose(
                x_m=float(candidate.translation[0]),
                y_m=float(candidate.translation[1]),
                z_m=float(candidate.translation[2]),
                qw=float(candidate.quaternion_wxyz[0]),
                qx=float(candidate.quaternion_wxyz[1]),
                qy=float(candidate.quaternion_wxyz[2]),
                qz=float(candidate.quaternion_wxyz[3]),
            )
            corners = [by_id[key].corners for key in candidate.tag_ids if key in by_id]
            points = np.concatenate(corners) if corners else np.empty((0, 2))
            # Sum of tag quadrilateral area (clipped to image fraction); spread
            # is the bounding rectangle of all used corners, normalized.
            area = sum(
                abs(
                    float(
                        np.dot(c[:, 0], np.roll(c[:, 1], -1))
                        - np.dot(c[:, 1], np.roll(c[:, 0], -1))
                    )
                )
                / 2
                for c in corners
            )
            spread = float(np.prod(np.ptp(points, axis=0))) if len(points) else 0
            message.candidates.add(
                field_to_camera=pose,
                method=int(candidate.method),
                tag_ids=candidate.tag_ids,
                reprojection_error_px=candidate.reprojection_error_px,
                average_tag_distance_m=candidate.average_tag_distance_m,
                image_area_fraction=min(1.0, area / (w * h)),
                image_spread_fraction=min(1.0, spread / (w * h)),
                distortion_displacement_px=candidate.distortion_factor_px,
            )
    for detection in detections:
        tag = message.tags.add(
            id=detection.id,
            corners_xy_px=detection.corners.reshape(-1),
            hamming=detection.hamming,
            decision_margin=detection.decision_margin,
            used_for_pose=detection.id in solution.used_tag_ids,
            rejection_reason=(
                "tag-policy-excluded"
                if selection and detection.id not in selection.allowed_tag_ids
                else solution.rejection_reasons.get(detection.id, "")
            ),
        )
        if detection.distortion_factor_px is not None:
            tag.distortion_displacement_px = detection.distortion_factor_px
    message.timing.CopyFrom(
        wire.ProcessingTiming(
            capture_to_detect_ms=detected.capture_to_detect_ms,
            detect_ms=detected.batch.detect_ms,
            solve_ms=solution.solve_ms,
            total_ms=total_ms,
        )
    )
    validate_observation(message)
    return message


class BetaNtTransport:
    def __init__(
        self,
        config: NtConfig,
        configuration: ConfigurationService,
        cameras: Callable[[], list[wire.CameraGeneration]],
        *,
        instance=None,
        clock: ClockGate | None = None,
    ) -> None:
        import ntcore

        if config.mode != "client":
            raise ConfigError("beta robot mode requires Jetson NT4 client, roboRIO server")
        self.ntcore = ntcore
        self.configuration, self._cameras = configuration, cameras
        self.clock = clock or ClockGate()
        self.session = uuid.uuid4().hex
        self.started_ns = time.monotonic_ns()
        self._lock = threading.RLock()
        self._ack: wire.Acknowledgement | None = None
        self._ack_applied_ns = 0
        self._connection_after_us = 0
        self._health_sequence = 0
        self._last_clock: tuple[int, int] | None = None
        self._closed = False
        self._config = config
        self._last_resync_ns = 0
        self.last_error = ""
        self.withheld = 0
        self._robot_decisions, self._decisions_at = {}, 0.0
        self.instance = instance or ntcore.NetworkTableInstance.create()
        self._owns_instance = instance is None
        options = ntcore.PubSubOptions(
            keepDuplicates=True, sendAll=True, periodic=0.005, pollStorage=32
        )
        self._manifest = self.instance.getRawTopic(f"{ROOT}/robot/manifest").subscribe(
            "proto:spot.vision.v2.Manifest", b"", options
        )
        self._robot_state = self.instance.getRawTopic(f"{ROOT}/robot/state").subscribe(
            "proto:spot.vision.v2.RobotState", b"", options
        )
        self._decisions = self.instance.getStringTopic(f"{ROOT}/robot/decisions").subscribe(
            "", ntcore.PubSubOptions(periodic=1.0, pollStorage=2)
        )
        self._ack_publisher = self.instance.getRawTopic(f"{ROOT}/config/ack").publish(
            "proto:spot.vision.v2.Acknowledgement", options
        )
        self._health = self.instance.getRawTopic(f"{ROOT}/health").publish(
            "proto:spot.vision.v2.Health", options
        )
        self._observations: dict[str, object] = {}
        self._listeners = [
            self.instance.addConnectionListener(True, self._connection_event),
            self.instance.addTimeSyncListener(False, self._sync_event),
            self.instance.addListener(
                self._robot_state, ntcore.EventFlags.kValueRemote, self._state_event
            ),
        ]
        if self._owns_instance and config.enabled:
            if config.server:
                self.instance.setServer(config.server)
            elif config.team:
                self.instance.setServerTeam(config.team)
            else:
                raise ConfigError("beta NT client needs robot endpoint or team")
            self.instance.startClient4(config.identity)

    def _connection_event(self, event) -> None:
        connected = event.is_(self.ntcore.EventFlags.kConnected)
        with self._lock:
            self.clock.connection(uuid.uuid4().hex if connected else None)
            self._ack = None
            self._connection_after_us = nt_now_us()
            if connected:
                # Allow the initial exchange to arrive before retrying a
                # missing or rejected sample from a newly connected server.
                self._last_resync_ns = time.monotonic_ns()
        self.configuration.connection_changed(connected)

    def _sync_event(self, event) -> None:
        data = event.data
        # Offset getter must agree that synchronization exists on this exact
        # publishing instance; _now() alone has no such meaning.
        offset = self.instance.getServerTimeOffset()
        self.clock.update(offset if data.valid else None, data.rtt2, data.valid)

    def _state_event(self, event) -> None:
        try:
            value = event.data.value
            if value.time() < self._connection_after_us:
                return
            payload = value.getRaw()
            if len(payload) > 1024:
                return
            self.configuration.robot_state(wire.RobotState.FromString(payload))
        except Exception:
            LOGGER.debug("invalid robot state packet", exc_info=True)

    def poll(self) -> None:
        """Called by runtime supervisor; potentially expensive apply is off HTTP."""
        sync = self.clock.snapshot()
        # NTCore 2026.2.2 ClientImpl processes only the initial RTT response.
        # Its time-sync event is not a periodic heartbeat. Expiry therefore
        # requests a new built-in exchange by reconnecting; it never refreshes
        # validity merely by polling an unchanged cached offset. Qualification
        # must establish the maximum safe interval from measured drift.
        if (
            self._owns_instance
            and self._config.enabled
            and self.instance.isConnected()
            and sync.state != "Synchronized"
            and (sync.update_age_s is None or sync.update_age_s > self.clock.expiry_s)
            and time.monotonic_ns() - self._last_resync_ns > 1_000_000_000
        ):
            self._last_resync_ns = time.monotonic_ns()
            self.instance.stopClient()
            self.instance.startClient4(self._config.identity)
            return
        with self._lock:
            if self._ack is not None and (
                sync.state != "Synchronized"
                or self._ack.connection_epoch != sync.connection_epoch
                or self._ack.sync_epoch != sync.sync_epoch
            ):
                self._ack = None
        for sample in self._manifest.readQueue():
            if sync.state != "Synchronized" or sample.time < self._connection_after_us:
                continue
            try:
                manifest = parse_manifest(sample.value)
                self.configuration.accept_manifest(manifest)
                self.acknowledge()
                self.last_error = ""
            except (ConfigError, RuntimeError, OSError) as exc:
                self.last_error = str(exc)
                self._publish_rejection(str(exc))
        # Also handles robot states arriving just before the fresh manifest.
        for sample in self._robot_state.readQueue():
            if sample.time >= self._connection_after_us and len(sample.value) <= 1024:
                try:
                    self.configuration.robot_state(wire.RobotState.FromString(sample.value))
                except Exception:
                    LOGGER.debug("invalid robot state packet", exc_info=True)

        for sample in self._decisions.readQueue():
            if (
                sync.state != "Synchronized"
                or sample.time < self._connection_after_us
                or len(sample.value) > 65536
            ):
                continue
            try:
                document = json.loads(sample.value, parse_constant=lambda _: None)
                manifest = self.configuration.manifest
                if (
                    not isinstance(document, dict)
                    or not manifest
                    or type(document.get("fusion_enabled")) is not bool
                    or document["robot_session"] != manifest.robot_session
                    or document["manifest_hash"] != manifest.manifest_hash
                ):
                    continue
                values = document["cameras"]
                if not isinstance(values, dict) or len(values) > 32:
                    continue
                names = {c.name for c in manifest.profile.cameras}
                valid = {}
                for name, decision in values.items():
                    if name not in names or not isinstance(decision, dict):
                        continue
                    if (
                        type(decision.get("sequence")) is not int
                        or decision["sequence"] <= 0
                        or type(decision.get("fused")) is not bool
                        or not isinstance(decision.get("state"), str)
                        or len(decision["state"]) > 64
                        or not isinstance(decision.get("capture_epoch"), str)
                        or not 1 <= len(decision["capture_epoch"]) <= 128
                        or decision.get("runtime_generation")
                        != self.configuration.acknowledged_generation
                        or decision.get("service_session") != self.session
                        or decision.get("connection_epoch") != sync.connection_epoch
                        or decision.get("sync_epoch") != sync.sync_epoch
                    ):
                        continue
                    captured = decision.get("capture_fpga_s")
                    server_now = (
                        (nt_now_us() + sync.offset_us) / 1e6 if sync.offset_us is not None else None
                    )
                    if (
                        type(captured) not in (float, int)
                        or not math.isfinite(captured)
                        or server_now is None
                        or not -0.005 <= server_now - captured <= 0.5
                    ):
                        continue
                    fields = (
                        "state",
                        "fused",
                        "capture_epoch",
                        "sequence",
                        "capture_fpga_s",
                        "service_session",
                        "runtime_generation",
                        "connection_epoch",
                        "sync_epoch",
                    )
                    valid[name] = {
                        **{key: decision[key] for key in fields},
                        "fusion_enabled": document["fusion_enabled"],
                    }
                with self._lock:
                    self._robot_decisions, self._decisions_at = valid, time.monotonic()
            except (ValueError, KeyError, TypeError):
                LOGGER.debug("invalid robot decision telemetry", exc_info=True)

    @property
    def robot_decisions(self):
        with self._lock:
            sync = self.clock.snapshot()
            if (
                sync.state != "Synchronized"
                or self._ack is None
                or time.monotonic() - self._decisions_at > 1.5
            ):
                return {}
            return {
                name: value
                for name, value in self._robot_decisions.items()
                if value.get("runtime_generation") == self.configuration.acknowledged_generation
                and value.get("connection_epoch") == sync.connection_epoch
                and value.get("sync_epoch") == sync.sync_epoch
            }

    def acknowledge(self) -> None:
        with self._lock:
            sync = self.clock.snapshot()
            manifest = self.configuration.manifest
            if (
                sync.state != "Synchronized"
                or not self.configuration.fresh
                or manifest is None
                or not self.configuration.acknowledged_generation
            ):
                self._ack = None
                return
            ack = wire.Acknowledgement(
                schema_version=2,
                robot_id=manifest.profile.robot_id,
                robot_session=manifest.robot_session,
                manifest_hash=manifest.manifest_hash,
                service_session=self.session,
                connection_epoch=sync.connection_epoch,
                sync_epoch=sync.sync_epoch,
                runtime_generation=self.configuration.state.generation,
                field_hash=content_hash(manifest.profile.field),
                cameras=self._cameras(),
                applied=True,
                tag_selection_supported=True,
            )
            if self._ack is None or self._ack != ack:
                self._ack = ack
                self._ack_applied_ns = time.monotonic_ns()
                self._ack_publisher.set(ack.SerializeToString())

    def invalidate_configuration(self) -> None:
        # Every application attempt, including rollback, establishes a fresh
        # post-application capture boundary before publication can resume.
        with self._lock:
            self._ack = None
            self._robot_decisions, self._decisions_at = {}, 0.0

    def _publish_rejection(self, error: str) -> None:
        self._ack_publisher.set(
            wire.Acknowledgement(
                schema_version=2, service_session=self.session, applied=False, error=error
            ).SerializeToString()
        )

    def context(
        self, camera_name: str, captured_ns: int, uncertainty_s: float | None
    ) -> ObservationContext | None:
        with self._lock:
            sync = self.clock.snapshot()
            ack = self._ack
            if (
                ack is None
                or sync.state != "Synchronized"
                or ack.connection_epoch != sync.connection_epoch
                or ack.sync_epoch != sync.sync_epoch
                or ack.runtime_generation != self.configuration.acknowledged_generation
                or captured_ns - int((uncertainty_s or 0) * 1e9)
                <= max(sync.ready_since_ns, self._ack_applied_ns)
            ):
                return None
            camera = next((c for c in ack.cameras if c.camera_name == camera_name), None)
            if camera is None or not camera.binding_id:
                return None
            copied_ack = wire.Acknowledgement()
            copied_ack.CopyFrom(ack)
            copied_camera = next(c for c in copied_ack.cameras if c.camera_name == camera_name)
            return ObservationContext(
                copied_ack, copied_camera, self._ack_applied_ns, uncertainty_s
            )

    def publish(self, observation: wire.Observation, captured_ns: int) -> bool:
        validate_observation(observation)
        with self._lock:
            context = self.context(
                observation.camera_name, captured_ns, observation.timestamp_uncertainty_s
            )
            if (
                context is None
                or not observation.capture_epoch
                or observation.runtime_generation != context.acknowledgement.runtime_generation
                or observation.sync_epoch != context.acknowledgement.sync_epoch
                or observation.connection_epoch != context.acknowledgement.connection_epoch
                or observation.robot_session != context.acknowledgement.robot_session
                or observation.manifest_hash != context.acknowledgement.manifest_hash
                or observation.field_hash != context.acknowledgement.field_hash
                or observation.binding_id != context.camera.binding_id
                or observation.binding_generation != context.camera.binding_generation
                or observation.mode_id != context.camera.mode_id
                or observation.optical_signature != context.camera.optical_signature
                or observation.calibration_hash != context.camera.calibration_hash
                or observation.calibration_valid != context.camera.calibration_valid
                or observation.service_session != self.session
            ):
                self.withheld += 1
                return False
            selection = self.configuration.tag_selection()
            if (
                selection is None
                or observation.tag_selection_generation != selection.generation
                or any(
                    tag not in selection.allowed_tag_ids
                    for candidate in observation.candidates
                    for tag in candidate.tag_ids
                )
            ):
                self.withheld += 1
                return False
            now = nt_now_us()
            age_s = (now - observation.capture_local_nt_us) / 1e6
            manifest = self.configuration.manifest
            if manifest is None or not (
                -manifest.profile.future_tolerance_s <= age_s <= manifest.profile.max_age_s
            ):
                self.withheld += 1
                return False
            publisher = self._observations.get(observation.camera_name)
            if publisher is None:
                publisher = self.instance.getRawTopic(
                    f"{ROOT}/{observation.camera_name}/observations"
                ).publish(
                    "proto:spot.vision.v2.Observation",
                    self.ntcore.PubSubOptions(keepDuplicates=True, sendAll=True, periodic=0.005),
                )
                self._observations[observation.camera_name] = publisher
            publisher.set(observation.SerializeToString(), observation.capture_local_nt_us)
            return True

    def heartbeat(self, package_path: str = "", faults: list[str] | None = None) -> wire.Health:
        now_ns, local_us = time.monotonic_ns(), nt_now_us()
        if self._last_clock is not None:
            prior_ns, prior_us = self._last_clock
            if abs((local_us - prior_us) - (now_ns - prior_ns) // 1000) > self.clock.jump_us:
                self.clock.invalidate_jump()
        self._last_clock = now_ns, local_us
        sync = self.clock.snapshot(now_ns)
        self._health_sequence += 1
        message = wire.Health(
            schema_version=2,
            service_session=self.session,
            sequence=self._health_sequence,
            uptime_s=(now_ns - self.started_ns) / 1e9,
            sync_state=sync.state,
            offset_us=sync.offset_us or 0,
            sync_update_age_s=sync.update_age_s or 0,
            connection_epoch=sync.connection_epoch,
            sync_epoch=sync.sync_epoch,
            discontinuities=sync.discontinuities,
            runtime_generation=self.configuration.state.generation,
            release_id=package_path,
            faults=faults or [],
        )
        self._health.set(message.SerializeToString(), local_us)
        return message

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for listener in self._listeners:
            self.instance.removeListener(listener)
        for resource in [
            self._manifest,
            self._decisions,
            self._robot_state,
            self._ack_publisher,
            self._health,
            *self._observations.values(),
        ]:
            resource.close()
        if self._owns_instance:
            self.instance.stopClient()
            self.ntcore.NetworkTableInstance.destroy(self.instance)
