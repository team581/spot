from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from .capture import CaptureWorker
from .config import Calibration, ConfigError, ServiceConfig, load_calibration
from .health import Watchdog, jetson_temperature_c
from .models import CameraCounters
from .native import Detector, create_detector
from .pose import FieldLayout, PoseSolver, robot_from_camera_transform, select_robot_pose
from .queues import FairResultQueue, LatestFrameSlot, ResultQueue
from .scheduler import FairDetectorScheduler
from .transport import NtPublisher, make_vision_frame

LOGGER = logging.getLogger(__name__)


class OutputWorker(threading.Thread):
    def __init__(
        self,
        config: ServiceConfig,
        cameras: dict,
        counters: dict[str, CameraCounters],
        solvers: dict[str, PoseSolver],
        queue: ResultQueue,
        publisher: NtPublisher,
        stop_event: threading.Event,
        field_revision: int,
    ) -> None:
        super().__init__(name="pose-and-output", daemon=True)
        self.config = config
        self.cameras = cameras
        self.counters = counters
        self.solvers = solvers
        self.queue = queue
        self.publisher = publisher
        self.stop_event = stop_event
        self.field_revision = field_revision
        self.last_progress_monotonic = time.monotonic()
        self.robot_from_cameras = {
            camera_id: robot_from_camera_transform(
                camera.robot_from_camera_translation,
                camera.robot_from_camera_rpy_deg,
            )
            for camera_id, camera in cameras.items()
        }

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.last_progress_monotonic = time.monotonic()
            detected = self.queue.get(timeout=0.1)
            if detected is None:
                continue
            camera_id = detected.frame.camera_id
            try:
                solution = self.solvers[camera_id].solve(detected.batch.detections)
            except Exception as exc:
                self.counters[camera_id].error = f"Pose solver: {exc}"
                LOGGER.warning("camera %s pose solve failed: %s", camera_id, exc)
                continue
            total_ms = (time.monotonic_ns() - detected.frame.captured_monotonic_ns) / 1e6
            message = make_vision_frame(
                self.config, self.cameras[camera_id], detected, solution, total_ms
            )
            # Use the effective layout revision when the config requested automatic hashing.
            message.field_revision = self.field_revision
            temperature_c = jetson_temperature_c()
            robot_pose = select_robot_pose(solution, self.robot_from_cameras[camera_id])
            self.publisher.publish_frame(
                self.cameras[camera_id],
                self.field_revision,
                message,
                detected.frame.capture_timestamp_us,
                self.counters[camera_id],
                temperature_c,
                robot_pose,
            )
            LOGGER.debug(
                "frame camera=%s sequence=%d tags=%d candidates=%d total_ms=%.3f",
                camera_id,
                message.sequence,
                len(message.tags),
                len(message.candidates),
                total_ms,
            )


@dataclass
class VisionService:
    config: ServiceConfig

    def __post_init__(self) -> None:
        self.stop_event = threading.Event()
        self._closed = False
        self.wake_event = threading.Event()
        enabled = [camera for camera in self.config.cameras if camera.enabled]
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
                    calibration = None
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
                self.layout = FieldLayout.load(self.config.field_layout, self.config.field_revision)
            except ConfigError as exc:
                LOGGER.warning("field-relative pose output disabled: %s", exc)
                for counter in self.counters.values():
                    counter.configuration_error = str(exc)
                    counter.error = str(exc)
        self.field_revision = self.layout.revision if self.layout else self.config.field_revision
        self.detectors: dict[str, Detector] = {}
        usable = []
        for camera in enabled:
            try:
                self.detectors[camera.id] = create_detector(camera, self.calibrations[camera.id])
                usable.append(camera)
            except Exception as exc:
                self.counters[camera.id].configuration_error = f"Detector initialization: {exc}"
                self.counters[camera.id].error = self.counters[camera.id].configuration_error
                LOGGER.warning("camera %s detector unavailable: %s", camera.id, exc)
        self.solvers = {
            camera.id: PoseSolver(self.calibrations[camera.id], self.layout, self.config.tag_size_m)
            for camera in enabled
        }
        self.slots = {camera.id: LatestFrameSlot(self.wake_event) for camera in enabled}
        per_camera_capacity = max(1, self.config.result_queue_capacity // max(1, len(enabled)))
        self.result_queue = FairResultQueue([camera.id for camera in enabled], per_camera_capacity)
        self.capture_workers = [
            CaptureWorker(
                camera,
                self.slots[camera.id],
                self.counters[camera.id],
                self.stop_event,
            )
            for camera in enabled
        ]
        self.scheduler = FairDetectorScheduler(
            [camera.id for camera in usable],
            self.slots,
            self.detectors,
            self.counters,
            self.result_queue,
            self.wake_event,
            self.stop_event,
        )
        self.publisher = NtPublisher(self.config.nt, [camera.id for camera in enabled])
        self.output_worker = OutputWorker(
            self.config,
            self.cameras,
            self.counters,
            self.solvers,
            self.result_queue,
            self.publisher,
            self.stop_event,
            self.field_revision,
        )
        self.watchdog = Watchdog()

    def start(self) -> None:
        self.publisher.publish_global()
        for camera_id, camera in self.cameras.items():
            calibration = self.calibrations[camera_id]
            self.publisher.publish_calibration_status(
                camera, bool(calibration is not None and calibration.provisional)
            )
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
                    for camera_id, counter in self.counters.items()
                )
                LOGGER.debug(
                    "service status %s",
                    summary,
                )
                now = time.monotonic()
                failed = [
                    worker.name
                    for worker in (self.scheduler, self.output_worker)
                    if not worker.is_alive() or now - worker.last_progress_monotonic > 2.0
                ]
                if failed:
                    raise RuntimeError("pipeline workers stalled: " + ", ".join(failed))
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
