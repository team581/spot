from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .capture import CaptureWorker
from .config import Calibration, ConfigError, ServiceConfig, load_calibration
from .health import Watchdog, jetson_temperature_c
from .models import CameraCounters, DetectedFrame, FramePacket
from .native import Detector, create_detector
from .pose import FieldLayout, PoseSolver, robot_from_camera_transform, select_robot_pose
from .queues import BoundedDropOldestQueue, LatestFrameSlot
from .scheduler import FairDetectorScheduler
from .transport import NtPublisher, make_vision_frame

LOGGER = logging.getLogger(__name__)


class OutputWorker(threading.Thread):
    def __init__(self, config: ServiceConfig, cameras: dict, counters: dict[str, CameraCounters],
                 solvers: dict[str, PoseSolver], queue: BoundedDropOldestQueue[DetectedFrame],
                 publisher: NtPublisher, stop_event: threading.Event,
                 field_revision: int, frame_observer: Callable[[FramePacket], None] | None = None) -> None:
        super().__init__(name="pose-and-output", daemon=True)
        self.config = config
        self.cameras = cameras
        self.counters = counters
        self.solvers = solvers
        self.queue = queue
        self.publisher = publisher
        self.stop_event = stop_event
        self.field_revision = field_revision
        self.frame_observer = frame_observer
        self.robot_from_cameras = {
            camera_id: robot_from_camera_transform(
                camera.robot_from_camera_translation,
                camera.robot_from_camera_rpy_deg,
            )
            for camera_id, camera in cameras.items()
        }

    def run(self) -> None:
        while not self.stop_event.is_set():
            detected = self.queue.get(timeout=0.1)
            if detected is None:
                continue
            camera_id = detected.frame.camera_id
            solution = self.solvers[camera_id].solve(detected.batch.detections)
            if self.frame_observer is not None:
                try:
                    self.frame_observer(detected.frame)
                except Exception:  # disposable debug observer must not affect output
                    LOGGER.debug("frame observer failed for %s", camera_id, exc_info=True)
            total_ms = (time.monotonic_ns() - detected.frame.captured_monotonic_ns) / 1e6
            message = make_vision_frame(
                self.config, self.cameras[camera_id], detected, solution, total_ms)
            # Use the effective layout revision when the config requested automatic hashing.
            message.field_revision = self.field_revision
            temperature_c = jetson_temperature_c()
            robot_pose = select_robot_pose(solution, self.robot_from_cameras[camera_id])
            self.publisher.publish_frame(
                self.cameras[camera_id], self.field_revision, message,
                detected.frame.capture_timestamp_us, self.counters[camera_id],
                temperature_c, robot_pose,
            )
            LOGGER.debug(
                "frame camera=%s sequence=%d tags=%d candidates=%d total_ms=%.3f",
                camera_id, message.sequence, len(message.tags), len(message.candidates), total_ms,
                extra={"prototype": {
                    "type": "frame",
                    "camera_id": camera_id,
                    "sequence": message.sequence,
                    "state": self.counters[camera_id].state.value,
                    "tags": [{
                        "id": tag.id,
                        "corners": list(tag.corners_xy_px),
                        "hamming": tag.hamming,
                        "decision_margin": tag.decision_margin,
                    } for tag in message.tags],
                    "candidate_count": len(message.candidates),
                    "capture_fps": self.counters[camera_id].fps_capture,
                    "detect_fps": self.counters[camera_id].fps_detect,
                    "timing": {
                        "capture_to_detect_ms": message.timing.capture_to_detect_ms,
                        "detect_ms": message.timing.detect_ms,
                        "solve_ms": message.timing.solve_ms,
                        "total_ms": message.timing.total_ms,
                    },
                    "drops": {
                        "capture": self.counters[camera_id].capture_failures,
                        "decode": self.counters[camera_id].decode_failures,
                        "overwrite": self.counters[camera_id].overwritten_before_processing,
                        "result_queue": self.counters[camera_id].result_queue_drops,
                        "sequence": self.counters[camera_id].driver_sequence_gaps,
                    },
                    "temperature_c": temperature_c,
                }},
            )


@dataclass
class VisionService:
    config: ServiceConfig
    frame_observer: Callable[[FramePacket], None] | None = None

    def __post_init__(self) -> None:
        self.stop_event = threading.Event()
        self._closed = False
        self.wake_event = threading.Event()
        enabled = [camera for camera in self.config.cameras if camera.enabled]
        if not enabled:
            raise ConfigError("at least one camera must be enabled")
        self.cameras = {camera.id: camera for camera in enabled}
        self.counters = {camera.id: CameraCounters() for camera in enabled}
        self.calibrations: dict[str, Calibration | None] = {}
        for camera in enabled:
            calibration = None
            if camera.calibration:
                try:
                    calibration = load_calibration(camera.calibration)
                    calibration.validate_for(camera)
                    calibration = calibration.for_image_rotation(camera)
                except ConfigError as exc:
                    self.counters[camera.id].configuration_error = str(exc)
                    self.counters[camera.id].error = str(exc)
                    LOGGER.warning("camera %s pose output disabled: %s", camera.id, exc)
            if calibration is not None and calibration.provisional:
                LOGGER.warning(
                    "camera %s uses provisional calibration; pose accuracy is not production-ready",
                    camera.id,
                )
            self.calibrations[camera.id] = calibration

        self.layout = None
        if self.config.field_layout:
            try:
                self.layout = FieldLayout.load(
                    self.config.field_layout, self.config.field_revision)
            except ConfigError as exc:
                LOGGER.warning("field-relative pose output disabled: %s", exc)
                for counter in self.counters.values():
                    counter.configuration_error = str(exc)
                    counter.error = str(exc)
        self.field_revision = self.layout.revision if self.layout else self.config.field_revision
        self.detectors: dict[str, Detector] = {
            camera.id: create_detector(camera, self.calibrations[camera.id]) for camera in enabled
        }
        self.solvers = {
            camera.id: PoseSolver(self.calibrations[camera.id], self.layout,
                                  self.config.tag_size_m)
            for camera in enabled
        }
        self.slots = {camera.id: LatestFrameSlot(self.wake_event) for camera in enabled}
        self.result_queue: BoundedDropOldestQueue[DetectedFrame] = BoundedDropOldestQueue(
            self.config.result_queue_capacity)
        self.capture_workers = [CaptureWorker(
            camera, self.slots[camera.id], self.counters[camera.id], self.stop_event)
            for camera in enabled]
        self.scheduler = FairDetectorScheduler(
            [camera.id for camera in enabled], self.slots, self.detectors, self.counters,
            self.result_queue, self.wake_event, self.stop_event,
        )
        self.publisher = NtPublisher(self.config.nt, [camera.id for camera in enabled])
        self.output_worker = OutputWorker(
            self.config, self.cameras, self.counters, self.solvers, self.result_queue,
            self.publisher, self.stop_event, self.field_revision, self.frame_observer,
        )
        self.watchdog = Watchdog()

    def start(self) -> None:
        self.publisher.publish_global(self.config.schema_version)
        for camera_id, camera in self.cameras.items():
            calibration = self.calibrations[camera_id]
            self.publisher.publish_calibration_status(camera, bool(
                calibration is not None and calibration.provisional))
        for worker in self.capture_workers:
            worker.start()
        self.scheduler.start()
        self.output_worker.start()
        self.watchdog.ready()

    def run_forever(self) -> None:
        self.start()
        try:
            while not self.stop_event.wait(1.0):
                summary = ", ".join(
                    f"{camera_id}:{counter.state.value}/{counter.fps_detect:.1f}fps"
                    for camera_id, counter in self.counters.items())
                LOGGER.debug(
                    "service status %s", summary,
                    extra={"prototype": {
                        "type": "status",
                        "temperature_c": jetson_temperature_c(),
                        "cameras": {
                            camera_id: counter.snapshot()
                            for camera_id, counter in self.counters.items()
                        },
                    }},
                )
                self.watchdog.ping(summary)
        finally:
            self.stop()

    def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop_event.set()
        self.wake_event.set()
        for slot in self.slots.values():
            slot.close()
        self.result_queue.close()
        for thread in [*self.capture_workers, self.scheduler, self.output_worker]:
            if thread.is_alive():
                thread.join(timeout=3.0)
        self.publisher.close()
        self.watchdog.stopping()
