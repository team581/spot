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


def test_extended_lens_model_uses_cpu_without_constructing_cuda(monkeypatch):
    from dataclasses import replace
    from pathlib import Path

    from spot_vision import _spot_cuda
    from spot_vision.config import load_calibration, load_config
    from spot_vision.native import NativeDetector, create_detector

    root = Path(__file__).parent / "data" / "regression"
    camera = load_config(root / "config.json").camera("front")
    camera = replace(
        camera, detector=replace(camera.detector, backend="cuda", fallback_to_cpu=True)
    )
    calibration = replace(
        load_calibration(camera.calibration),
        distortion=(-0.18, 0.04, 0.006, -0.008, 0.01, 0.1, 0.0, 0.0),
    )
    monkeypatch.setattr(_spot_cuda, "CUDA_AVAILABLE", True)

    def unexpected_cuda(*args):
        raise AssertionError("unsupported coefficients must not reach CUDA refinement")

    monkeypatch.setattr(_spot_cuda, "CudaDetector", unexpected_cuda, raising=False)
    result = create_detector(camera, calibration)
    assert isinstance(result, NativeDetector)
    assert isinstance(result.implementation, _spot_cuda.CpuDetector)
    assert result.calibration == calibration
    import pytest

    camera = replace(camera, detector=replace(camera.detector, fallback_to_cpu=False))
    with pytest.raises(RuntimeError, match="five-coefficient"):
        create_detector(camera, calibration)
