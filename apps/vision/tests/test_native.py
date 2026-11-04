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


def test_cpu_detection_with_calibration_does_not_require_native_extension(monkeypatch):
    import sys
    from dataclasses import replace
    from pathlib import Path

    import spot_vision
    from spot_vision.cli import _recording_frames
    from spot_vision.config import load_calibration, load_config
    from spot_vision.native import CpuDetector, create_detector
    from spot_vision.uncertainty import distortion_factors

    monkeypatch.delattr(spot_vision, "_spot_cuda", raising=False)
    monkeypatch.setitem(sys.modules, "spot_vision._spot_cuda", None)
    root = Path(__file__).parent / "data" / "regression"
    camera = load_config(root / "config.json").camera("front")
    camera = replace(camera, detector=replace(camera.detector, backend="cpu"))
    calibration = load_calibration(camera.calibration)
    detector = create_detector(camera, calibration)
    assert isinstance(detector, CpuDetector)
    frame = next(_recording_frames(root / "center.png", camera))
    batch = detector.detect(frame)
    assert [d.id for d in batch.detections] == [1]
    expected = distortion_factors(np.asarray([d.corners for d in batch.detections]), calibration)
    assert np.allclose([d.distortion_factor_px for d in batch.detections], expected)


def test_extended_lens_model_uses_cpu_without_constructing_cuda(monkeypatch, cuda_native):
    from dataclasses import replace
    from pathlib import Path

    from spot_vision.config import load_calibration, load_config
    from spot_vision.native import CpuDetector, create_detector

    root = Path(__file__).parent / "data" / "regression"
    camera = load_config(root / "config.json").camera("front")
    camera = replace(
        camera, detector=replace(camera.detector, backend="cuda", fallback_to_cpu=True)
    )
    calibration = replace(
        load_calibration(camera.calibration),
        distortion=(-0.18, 0.04, 0.006, -0.008, 0.01, 0.1, 0.0, 0.0),
    )

    def unexpected_cuda(*args):
        raise AssertionError("unsupported coefficients must not reach CUDA refinement")

    monkeypatch.setattr(cuda_native, "CudaDetector", unexpected_cuda, raising=False)
    result = create_detector(camera, calibration)
    assert isinstance(result, CpuDetector)
    assert result.calibration == calibration
    import pytest

    camera = replace(camera, detector=replace(camera.detector, fallback_to_cpu=False))
    with pytest.raises(RuntimeError, match="five-coefficient"):
        create_detector(camera, calibration)
