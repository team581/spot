from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from spot_vision import scheduler as scheduler_module
from spot_vision.models import CameraCounters, DetectionBatch, FramePacket
from spot_vision.queues import BoundedDropOldestQueue, LatestFrameSlot
from spot_vision.scheduler import FairDetectorScheduler


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


def test_detection_fps_counts_completed_frames_without_burst_inflation(monkeypatch):
    stop, wake = threading.Event(), threading.Event()
    slot = LatestFrameSlot(wake)
    timestamps = [0] + [t for i in range(10) for t in (i * 100 + 1, (i + 1) * 100)]
    clock = iter(t * 1_000_000 for t in timestamps)
    image = np.zeros((8, 8, 2), dtype=np.uint8)
    frames = iter(FramePacket("a", i, i, 0, 0, image) for i in range(len(timestamps)))
    slot.put(next(frames))

    class Detector:
        def detect(self, image):
            following = next(frames, None)
            if following is None:
                stop.set()
            else:
                slot.put(following)
            return DetectionBatch((), 1.0, image.ctypes.data)

    counters = {"a": CameraCounters()}
    scheduler = FairDetectorScheduler(["a"], {"a": slot}, {"a": Detector()}, counters,
                                      BoundedDropOldestQueue(32), wake, stop)
    monkeypatch.setattr(scheduler_module.time, "monotonic_ns", lambda: next(clock))
    scheduler.run()
    assert counters["a"].detected == len(timestamps)
    assert counters["a"].fps_detect == pytest.approx(20)
