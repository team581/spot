from __future__ import annotations

import numpy as np
import pytest


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


def test_extended_lens_model_is_rejected_before_constructing_cuda(monkeypatch, cuda_native):
    from dataclasses import replace
    from pathlib import Path

    from spot_vision.config import load_calibration, load_config
    from spot_vision.native import create_detector

    root = Path(__file__).parent / "data" / "regression"
    camera = load_config(root / "config.json").camera("front")
    camera = replace(camera, detector=replace(camera.detector, backend="cuda"))
    calibration = replace(
        load_calibration(camera.calibration),
        distortion=(-0.18, 0.04, 0.006, -0.008, 0.01, 0.1, 0.0, 0.0),
    )

    def unexpected_cuda(*args):
        raise AssertionError("unsupported coefficients must not reach CUDA refinement")

    monkeypatch.setattr(cuda_native, "CudaDetector", unexpected_cuda, raising=False)
    with pytest.raises(RuntimeError, match="five-coefficient"):
        create_detector(camera, calibration)


def test_cuda_initialization_failure_propagates_without_constructing_cpu(monkeypatch, cuda_native):
    from dataclasses import replace
    from pathlib import Path

    from spot_vision import native
    from spot_vision.config import load_config

    camera = load_config(Path(__file__).parent / "data/regression/config.json").camera("front")
    camera = replace(camera, detector=replace(camera.detector, backend="cuda", decimate=2.0))

    def fail(*_):
        raise RuntimeError("GPU initialization failed")

    monkeypatch.setattr(cuda_native, "CudaDetector", fail)
    monkeypatch.setattr(native, "CpuDetector", lambda *_: pytest.fail("CPU fallback constructed"))
    with pytest.raises(RuntimeError, match="GPU initialization failed"):
        native.create_detector(camera, None)
