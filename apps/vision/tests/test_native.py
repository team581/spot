from __future__ import annotations

import numpy as np
import pytest


@pytest.mark.parametrize("quarter_turns", range(4))
def test_cpu_preserves_canonical_corner_order_and_pixel_origin(quarter_turns):
    from pathlib import Path

    import cv2

    from spot_vision.config import DetectorConfig
    from spot_vision.native import CpuDetector

    # The official artwork includes a one-cell white margin. Its black-square
    # edges give independent, exact upstream AprilTag pixel coordinates.
    artwork = cv2.imread(
        str(Path(__file__).parent / "data/regression/official-tag4.png"),
        cv2.IMREAD_GRAYSCALE,
    )
    image = np.full((480, 640), 255, dtype=np.uint8)
    image[80:400, 160:480] = cv2.resize(artwork, (320, 320), interpolation=cv2.INTER_NEAREST)
    expected = np.array([[192, 368], [448, 368], [448, 112], [192, 112]])
    for _ in range(quarter_turns):
        expected = np.column_stack((expected[:, 1], image.shape[1] - expected[:, 0]))
        image = np.rot90(image).copy()
    frame = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), cv2.COLOR_BGR2YUV_YUY2)
    batch = CpuDetector(frame.shape[1], frame.shape[0], DetectorConfig()).detect(frame)
    assert [tag.id for tag in batch.detections] == [4]
    assert np.allclose(batch.detections[0].corners, expected, atol=0.05, rtol=0)


def test_cpu_detection_with_calibration_does_not_require_native_extension(monkeypatch):
    import sys
    from dataclasses import replace
    from pathlib import Path

    import spot_vision
    from spot_vision.config import load_calibration, load_config
    from spot_vision.native import CpuDetector, create_detector
    from spot_vision.regression import load_image_frame
    from spot_vision.uncertainty import distortion_factors

    monkeypatch.delattr(spot_vision, "_spot_cuda", raising=False)
    monkeypatch.setitem(sys.modules, "spot_vision._spot_cuda", None)
    root = Path(__file__).parent / "data" / "regression"
    camera = load_config(root / "config.json").camera("front")
    camera = replace(camera, detector=replace(camera.detector, backend="cpu"))
    calibration = load_calibration(camera.calibration)
    detector = create_detector(camera, calibration)
    assert isinstance(detector, CpuDetector)
    frame = load_image_frame(root / "center.png", camera)
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
    camera = replace(camera, detector=replace(camera.detector, backend="cuda"))

    def fail(*_):
        raise RuntimeError("GPU initialization failed")

    monkeypatch.setattr(cuda_native, "CudaDetector", fail)
    monkeypatch.setattr(native, "CpuDetector", lambda *_: pytest.fail("CPU fallback constructed"))
    with pytest.raises(RuntimeError, match="GPU initialization failed"):
        native.create_detector(camera, None)
