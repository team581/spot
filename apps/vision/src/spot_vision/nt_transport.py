"""Typed NT configuration and self-contained vision observations."""

from __future__ import annotations

import copy
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from . import protocol_models as wire
from .clock import NtClock, nt_now_us
from .config import ConfigError, NtConfig
from .configuration import ConfigurationService, TagSelection
from .contract import MAX_TAGS, validate_observation
from .models import DetectedFrame, PoseSolution
from .protocol import ConfigurationIncomplete, ProfileSubscriber
from .structs import (
    DECISIONS,
    CameraSettings,
    FrameResult,
    Heartbeat,
    RobotDecision,
    RobotStatus,
    result_value,
    session,
    tag_ids,
)

ROOT = "/Spot"


@dataclass(frozen=True)
class ObservationContext:
    generation: str
    camera: wire.CameraDefinition
    calibrated: bool
    timestamp_uncertainty_s: float | None


def make_observation(
    detected: DetectedFrame,
    solution: PoseSolution,
    context: ObservationContext,
    total_ms: float,
    *,
    selection: TagSelection | None = None,
) -> wire.Observation:
    camera, frame = context.camera, detected.frame
    message = wire.Observation(
        tag_selection_generation=selection.generation if selection else 0,
        capture_epoch=frame.capture_epoch,
        sequence=frame.sequence,
        camera_name=camera.name,
        runtime_generation=context.generation,
        robot_to_camera=copy.deepcopy(camera.robot_to_camera),
        calibration_valid=context.calibrated,
        capture_local_nt_us=frame.capture_timestamp_us,
        timestamp_source=frame.timestamp_source,
        timestamp_uncertainty_s=context.timestamp_uncertainty_s or 0,
    )
    detections = detected.batch.detections[:MAX_TAGS]
    by_id = {tag.id: tag for tag in detections}
    h, w = frame.image.shape[:2]
    if context.calibrated and context.timestamp_uncertainty_s is not None:
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
            message.candidates.append(
                wire.PoseCandidate(
                    field_to_camera=pose,
                    method=int(candidate.method),
                    tag_ids=list(candidate.tag_ids),
                    reprojection_error_px=candidate.reprojection_error_px,
                    average_tag_distance_m=candidate.average_tag_distance_m,
                    image_area_fraction=min(1.0, area / (w * h)),
                    image_spread_fraction=min(1.0, spread / (w * h)),
                    distortion_displacement_px=candidate.distortion_factor_px,
                )
            )
    message.tags = [
        wire.TagObservation(detection.id, detection.corners.reshape(-1).tolist())
        for detection in detections
    ]
    message.timing = copy.deepcopy(
        wire.ProcessingTiming(
            capture_to_detect_ms=detected.capture_to_detect_ms,
            detect_ms=detected.batch.detect_ms,
            solve_ms=solution.solve_ms,
            total_ms=total_ms,
        )
    )
    validate_observation(message)
    return message


class NtTransport:
    def __init__(
        self,
        config: NtConfig,
        configuration: ConfigurationService,
        camera_ready: Callable[[str], bool],
        *,
        instance=None,
    ) -> None:
        import ntcore

        if config.mode != "client":
            raise ConfigError("Spot must be an NT client of the robot")
        self.ntcore = ntcore
        self.configuration, self._camera_ready = configuration, camera_ready
        self.instance = instance or ntcore.NetworkTableInstance.create()
        self._owns_instance = instance is None
        self.clock = NtClock(self.instance)
        self._lock = threading.RLock()
        self._config = config
        self._closed = False
        self._generation = ""
        self._applied_ns = time.monotonic_ns()
        self.withheld = 0
        self._observations = {}
        self._settings = {}
        self._decisions = {}
        self._profile = ProfileSubscriber(self.instance)
        options = ntcore.PubSubOptions(keepDuplicates=True, sendAll=True, periodic=0.02)
        self._robot_state = self.instance.getStructTopic(
            f"{ROOT}/robot/state", RobotStatus
        ).subscribe(RobotStatus(), options)
        self._health = self.instance.getStructTopic(f"{ROOT}/health", Heartbeat).publish(options)
        self._error = self.instance.getStringTopic(f"{ROOT}/error").publish()
        self._camera_names = self.instance.getStringArrayTopic(f"{ROOT}/cameras").publish()
        self._listener = self.instance.addConnectionListener(True, self._connection_event)
        if self._owns_instance and config.enabled:
            self._start_client()

    def _start_client(self) -> None:
        if self._config.server:
            self.instance.setServer(self._config.server)
        elif self._config.team:
            self.instance.setServerTeam(self._config.team)
        else:
            raise ConfigError("NT client needs robot endpoint or team")
        self.instance.startClient4(self._config.identity)

    def set_endpoint(self, config: NtConfig) -> None:
        self.instance.stopClient()
        self.instance.waitForListenerQueue(1)
        self._config = config
        self.configuration.connection_changed(False)
        self.invalidate_configuration()
        if config.enabled:
            self._start_client()

    def _connection_event(self, event) -> None:
        connected = event.is_(self.ntcore.EventFlags.kConnected)
        self.configuration.connection_changed(connected)
        self.invalidate_configuration()

    def poll(self) -> None:
        if not self.configuration.connected:
            return
        try:
            self.configuration.accept_manifest(self._profile.read())
            self.configuration_applied()
            self._error.set("")
        except ConfigurationIncomplete:
            return
        except (ConfigError, RuntimeError, OSError, ValueError) as exc:
            self.configuration.fresh = False
            self._error.set(str(exc))
            return
        manifest = self.configuration.manifest
        if manifest is None:
            return
        state = self._robot_state.get()
        self.configuration.robot_state(
            wire.RobotState(
                state.selectionGeneration,
                tag_ids(state.allowedTags, manifest.profile.field),
            )
        )

    def configuration_applied(self) -> None:
        with self._lock:
            config = self.configuration
            if not config.fresh or config.manifest is None:
                return
            if self._generation != config.state.generation:
                self._generation = config.state.generation
                self._applied_ns = time.monotonic_ns()
            for camera in config.manifest.profile.cameras:
                if camera.name not in self._settings:
                    self._settings[camera.name] = self.instance.getStructTopic(
                        f"{ROOT}/{camera.name}/settings", CameraSettings
                    ).publish()
                    self._decisions[camera.name] = self.instance.getStructTopic(
                        f"{ROOT}/{camera.name}/decision", RobotDecision
                    ).subscribe(RobotDecision())
                self._settings[camera.name].set(CameraSettings(camera.enabled, camera.required))
            self._camera_names.set([camera.name for camera in config.manifest.profile.cameras])

    def invalidate_configuration(self) -> None:
        with self._lock:
            self._generation = ""
            self._applied_ns = time.monotonic_ns()

    def context(
        self, camera_name: str, captured_ns: int, uncertainty_s: float | None
    ) -> ObservationContext | None:
        with self._lock:
            config = self.configuration
            if (
                not self._generation
                or not config.fresh
                or config.manifest is None
                or self.clock.snapshot().offset_us is None
                or captured_ns - int((uncertainty_s or 0) * 1e9) <= self._applied_ns
            ):
                return None
            camera = next(
                (c for c in config.manifest.profile.cameras if c.name == camera_name), None
            )
            if camera is None or not camera.binding_id or not camera.enabled:
                return None
            return ObservationContext(
                self._generation,
                copy.deepcopy(camera),
                self._camera_ready(camera_name),
                uncertainty_s,
            )

    def publish(self, observation: wire.Observation, captured_ns: int) -> bool:
        with self._lock:
            context = self.context(
                observation.camera_name, captured_ns, observation.timestamp_uncertainty_s
            )
            selection = self.configuration.tag_selection()
            manifest = self.configuration.manifest
            if (
                context is None
                or observation.runtime_generation != context.generation
                or selection is None
                or manifest is None
                or observation.tag_selection_generation != selection.generation
                or any(
                    tag not in selection.allowed_tag_ids
                    for candidate in observation.candidates
                    for tag in candidate.tag_ids
                )
                or not -manifest.profile.future_tolerance_s
                <= (nt_now_us() - observation.capture_local_nt_us) / 1e6
                <= manifest.profile.max_age_s
            ):
                self.withheld += 1
                return False
            publisher = self._observations.get(observation.camera_name)
            if publisher is None:
                publisher = self.instance.getStructTopic(
                    f"{ROOT}/{observation.camera_name}/observations", FrameResult
                ).publish(
                    self.ntcore.PubSubOptions(keepDuplicates=True, sendAll=True, periodic=0.005)
                )
                self._observations[observation.camera_name] = publisher
            publisher.set(
                result_value(observation, manifest.profile.field), observation.capture_local_nt_us
            )
            return True

    @property
    def robot_decisions(self) -> dict:
        sync = self.clock.snapshot()
        if sync.offset_us is None:
            return {}
        now = (nt_now_us() + sync.offset_us) / 1e6
        result = {}
        for name, subscriber in self._decisions.items():
            value = subscriber.get()
            if 0 <= now - value.captureFpgaS <= 0.5 and 0 <= value.reason < len(DECISIONS):
                result[name] = {
                    "capture_epoch": struct.pack("<qq", value.captureHigh, value.captureLow).hex(),
                    "sequence": value.sequence,
                    "state": DECISIONS[value.reason],
                    "fused": value.fused,
                    "fusion_enabled": value.fusionEnabled,
                }
        return result

    def heartbeat(self) -> None:
        with self._lock:
            ready = bool(
                self._generation
                and self.configuration.fresh
                and self.clock.snapshot().offset_us is not None
            )
            self._health.set(Heartbeat(*session(self._generation), ready), nt_now_us())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.instance.removeListener(self._listener)
        for resource in (
            self._profile,
            self._robot_state,
            self._health,
            self._error,
            self._camera_names,
            *self._observations.values(),
            *self._settings.values(),
            *self._decisions.values(),
        ):
            resource.close()
        if self._owns_instance:
            self.instance.stopClient()
            self.ntcore.NetworkTableInstance.destroy(self.instance)
