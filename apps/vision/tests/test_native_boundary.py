"""Real detector validation, buffer ownership and tag/no-tag transitions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from spot_vision.config import DetectorConfig, load_config
from spot_vision.native import CpuDetector
from spot_vision.regression import load_image_frame

DATA = Path(__file__).parent / "data/regression"


@pytest.fixture
def detector():
    return CpuDetector(16, 8, DetectorConfig())


@pytest.mark.parametrize(
    "image,error",
    [
        (np.zeros((8, 16, 2), dtype=np.float32), TypeError),
        (np.zeros((8, 16), dtype=np.uint8), ValueError),
        (np.zeros((8, 16, 3), dtype=np.uint8), ValueError),
        (np.zeros((9, 16, 2), dtype=np.uint8), ValueError),
        (np.zeros((8, 16, 2), dtype=np.uint8)[:, ::-1], ValueError),
        (np.zeros((8, 32, 2), dtype=np.uint8)[:, ::2], ValueError),
        (np.asfortranarray(np.zeros((8, 16, 2), dtype=np.uint8)), ValueError),
    ],
)
def test_native_rejects_invalid_buffer_before_detection(detector, image, error):
    with pytest.raises(error):
        detector.detect(image)


def test_native_preserves_input_and_reports_original_pointer(detector):
    image = np.random.default_rng(581).integers(0, 256, (8, 16, 2), dtype=np.uint8)
    original = image.copy()
    image.flags.writeable = False
    result = detector.detect(image)
    assert result.input_address == image.ctypes.data
    assert result.detect_ms > 0
    assert np.array_equal(image, original)


@pytest.mark.parametrize("min_tag_px", [True, 7, 30001, 16.5])
def test_cpu_rejects_invalid_minimum_tag_size(min_tag_px):
    options = DetectorConfig(min_tag_px=min_tag_px)
    with pytest.raises(ValueError, match="min_tag_px"):
        CpuDetector(16, 8, options)


@pytest.mark.parametrize("min_contrast", [True, 0, 256, 3.5])
def test_cpu_rejects_invalid_minimum_contrast(min_contrast):
    options = DetectorConfig(min_contrast=min_contrast)
    with pytest.raises(ValueError, match="min_contrast"):
        CpuDetector(16, 8, options)


def test_real_detector_does_not_retain_tags_from_previous_frame():
    camera = load_config(DATA / "config.json").camera("front")
    tag = load_image_frame(DATA / "multi.png", camera)
    blank = load_image_frame(DATA / "blank.png", camera)
    detector = CpuDetector(camera.width, camera.height, DetectorConfig())
    for image, expected in [(tag, [1, 2]), (blank, []), (tag, [1, 2]), (blank, [])]:
        assert sorted(d.id for d in detector.detect(image).detections) == expected


def test_independent_native_detectors_can_run_concurrently():
    camera = load_config(DATA / "config.json").camera("front")
    image = load_image_frame(DATA / "center.png", camera)

    def detect(_):
        detector = CpuDetector(camera.width, camera.height, DetectorConfig())
        return [sorted(d.id for d in detector.detect(image).detections) for _ in range(3)]

    with ThreadPoolExecutor(4) as pool:
        assert list(pool.map(detect, range(4))) == [[[1]] * 3] * 4


@pytest.mark.parametrize("decimate", [1.0, 1.5, 3.0, 4.0])
def test_unsupported_cuda_decimation_never_reaches_fatal_native_constructor(
    monkeypatch, cuda_native, decimate
):
    from spot_vision.native import create_detector

    camera = load_config(DATA / "config.json").camera("front")
    camera = replace(
        camera,
        detector=replace(camera.detector, backend="cuda", decimate=decimate),
    )
    monkeypatch.setattr(
        cuda_native,
        "CudaDetector",
        lambda *_: pytest.fail("fatal constructor reached"),
        raising=False,
    )
    with pytest.raises(RuntimeError, match="requires decimate=2"):
        create_detector(camera, None)
