from __future__ import annotations

import logging
import threading
import time

from .clock import FrameRateCounter
from .models import CameraCounters, CameraState, DetectedFrame
from .native import Detector
from .queues import LatestFrameSlot, ResultQueue

LOGGER = logging.getLogger(__name__)


class FairDetectorScheduler(threading.Thread):
    def __init__(
        self,
        camera_ids: list[str],
        slots: dict[str, LatestFrameSlot],
        detectors: dict[str, Detector],
        counters: dict[str, CameraCounters],
        output: ResultQueue,
        wake_event: threading.Event,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="detector-scheduler", daemon=True)
        self.camera_ids = camera_ids
        self.slots = slots
        self.detectors = detectors
        self.counters = counters
        self.output = output
        self.wake_event = wake_event
        self.stop_event = stop_event
        self._cursor = 0
        self.last_progress_monotonic = time.monotonic()
        self._frame_rates = {camera_id: FrameRateCounter() for camera_id in camera_ids}

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.last_progress_monotonic = time.monotonic()
            handled = False
            for offset in range(len(self.camera_ids)):
                index = (self._cursor + offset) % len(self.camera_ids)
                camera_id = self.camera_ids[index]
                frame = self.slots[camera_id].take()
                if frame is None:
                    continue
                handled = True
                self._cursor = (index + 1) % len(self.camera_ids)
                try:
                    batch = self.detectors[camera_id].detect(frame.image)
                    completed_ns = time.monotonic_ns()
                    result = DetectedFrame(
                        frame=frame,
                        batch=batch,
                        capture_to_detect_ms=(completed_ns - frame.captured_monotonic_ns) / 1e6,
                    )
                    camera_counters = self.counters[camera_id]
                    now = completed_ns / 1e9
                    camera_counters.fps_detect = self._frame_rates[camera_id].update(now)
                    camera_counters.last_detection_monotonic = now
                    camera_counters.detected += 1
                    if camera_counters.configuration_error:
                        camera_counters.state = CameraState.CONFIG_MISMATCH
                    else:
                        camera_counters.state = (
                            CameraState.RUNNING if batch.detections else CameraState.NO_TARGETS
                        )
                    if self.output.put(result):
                        camera_counters.result_queue_drops += 1
                except Exception as exc:
                    self.counters[camera_id].error = f"detector: {exc}"
                    LOGGER.exception("detection failed for %s", camera_id)
            if not handled:
                self.wake_event.clear()
                self.wake_event.wait(0.05)
