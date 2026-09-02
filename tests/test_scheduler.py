from __future__ import annotations

import threading
import time

import numpy as np

from buddy_vision.models import CameraCounters, DetectionBatch, FramePacket
from buddy_vision.queues import BoundedDropOldestQueue, LatestFrameSlot
from buddy_vision.scheduler import FairDetectorScheduler


class FakeDetector:
    def __init__(self, camera_id, calls):
        self.camera_id = camera_id
        self.calls = calls

    def detect(self, frame):
        self.calls.append(self.camera_id)
        return DetectionBatch((), 1.0, frame.ctypes.data)

    def reset(self):
        pass


def packet(camera_id, sequence):
    image = np.zeros((8, 8, 2), dtype=np.uint8)
    return FramePacket(camera_id, sequence, sequence, sequence, time.monotonic_ns(), image)


def test_scheduler_services_ready_cameras_round_robin():
    stop = threading.Event()
    wake = threading.Event()
    slots = {camera: LatestFrameSlot(wake) for camera in ("a", "b")}
    calls = []
    detectors = {camera: FakeDetector(camera, calls) for camera in slots}
    counters = {camera: CameraCounters() for camera in slots}
    output = BoundedDropOldestQueue(8)
    scheduler = FairDetectorScheduler(list(slots), slots, detectors, counters, output, wake, stop)
    slots["a"].put(packet("a", 1))
    slots["b"].put(packet("b", 1))
    scheduler.start()
    deadline = time.monotonic() + 1
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    stop.set()
    wake.set()
    scheduler.join(1)
    assert calls[:2] == ["a", "b"]
