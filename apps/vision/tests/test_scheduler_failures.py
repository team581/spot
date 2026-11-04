"""One faulty camera cannot terminate detection for the remaining cameras."""

import threading
import time
from types import SimpleNamespace

import numpy as np

from spot_vision.models import CameraCounters, CameraState, DetectionBatch, FramePacket
from spot_vision.queues import BoundedDropOldestQueue, LatestFrameSlot
from spot_vision.scheduler import FairDetectorScheduler


def test_failed_camera_is_isolated_and_healthy_camera_still_publishes():
    stop, wake = threading.Event(), threading.Event()
    slots = {name: LatestFrameSlot(wake) for name in ["bad", "good"]}
    counters = {name: CameraCounters() for name in slots}
    calls = []

    def fail(_):
        calls.append("bad")
        raise RuntimeError("detector unplugged")

    def succeed(_):
        calls.append("good")
        stop.set()
        return DetectionBatch((), 1.0)

    detectors = {"bad": SimpleNamespace(detect=fail), "good": SimpleNamespace(detect=succeed)}
    for name, slot in slots.items():
        slot.put(FramePacket(name, 1, 1, 1, time.monotonic_ns(), np.zeros((8, 16, 2), np.uint8)))
    output = BoundedDropOldestQueue(1)
    FairDetectorScheduler(list(slots), slots, detectors, counters, output, wake, stop).run()
    assert calls == ["bad", "good"]
    assert counters["bad"].detected == 0 and "detector unplugged" in counters["bad"].error
    assert counters["good"].detected == 1 and counters["good"].state == CameraState.NO_TARGETS
    assert output.get(timeout=0).frame.camera_id == "good"


def test_result_overload_drops_oldest_and_counts_loss():
    stop, wake = threading.Event(), threading.Event()
    slot, output = LatestFrameSlot(wake), BoundedDropOldestQueue(1)
    counters = {"a": CameraCounters()}
    image = np.zeros((8, 16, 2), np.uint8)
    sequence = 0

    def enqueue():
        slot.put(FramePacket("a", sequence, sequence, sequence, time.monotonic_ns(), image))

    def detect(_):
        nonlocal sequence
        sequence += 1
        if sequence == 3:
            stop.set()
        else:
            enqueue()
        return DetectionBatch((), 1.0)

    enqueue()
    FairDetectorScheduler(
        ["a"], {"a": slot}, {"a": SimpleNamespace(detect=detect)}, counters, output, wake, stop
    ).run()
    assert counters["a"].detected == 3
    assert counters["a"].result_queue_drops == 2
    assert output.get(timeout=0).frame.sequence == 2
