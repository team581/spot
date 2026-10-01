from __future__ import annotations

import numpy as np

from spot_vision.models import DetectionBatch
from spot_vision.native import FallbackDetector


class FakeDetector:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        if self.fail:
            raise RuntimeError("detector failure")
        return DetectionBatch((), 1.0)

    def reset(self):
        self.calls = 0


def test_recoverable_cuda_failure_switches_permanently_to_cpu():
    primary = FakeDetector(fail=True)
    fallback = FakeDetector()
    detector = FallbackDetector(primary, fallback)
    frame = np.zeros((8, 8, 2), dtype=np.uint8)
    detector.detect(frame)
    detector.detect(frame)
    assert primary.calls == 1
    assert fallback.calls == 2
