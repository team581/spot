"""Real pybind detector validation, buffer ownership and tag/no-tag transitions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from spot_vision import _spot_cuda as native
from spot_vision.cli import _recording_frames
from spot_vision.config import load_config
from spot_vision.native import FallbackDetector

DATA = Path(__file__).parent / "data/regression"


@pytest.fixture
def detector():
    return native.CpuDetector(16, 8, native.DetectorOptions())


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
    assert detector.metrics().calls == 0


def test_native_preserves_input_and_reports_original_pointer(detector):
    image = np.random.default_rng(581).integers(0, 256, (8, 16, 2), dtype=np.uint8)
    original = image.copy()
    image.flags.writeable = False
    result = detector.detect(image)
    assert result.input_address == image.ctypes.data
    assert detector.metrics().last_input_address == image.ctypes.data
    assert np.array_equal(image, original)


def test_native_reset_clears_metrics_and_next_frame_remains_usable(detector):
    image = np.full((8, 16, 2), 128, dtype=np.uint8)
    for _ in range(3):
        assert not detector.detect(image).detections
    metrics = detector.metrics()
    assert metrics.calls == 3 and metrics.total_detect_ms >= metrics.last_detect_ms >= 0
    detector.reset()
    assert detector.metrics().calls == 0
    assert detector.metrics().total_detect_ms == 0
    assert detector.metrics().last_input_address == 0
    detector.detect(image)
    assert detector.metrics().calls == 1


@pytest.mark.parametrize("threads", [0, -1])
def test_native_rejects_invalid_thread_count(threads):
    options = native.DetectorOptions()
    options.threads = threads
    with pytest.raises(ValueError, match="threads"):
        native.CpuDetector(16, 8, options)


def test_real_detector_does_not_retain_tags_from_previous_frame():
    camera = load_config(DATA / "config.json").camera("front")
    tag = next(_recording_frames(DATA / "multi.png", camera))
    blank = next(_recording_frames(DATA / "blank.png", camera))
    detector = native.CpuDetector(camera.width, camera.height, native.DetectorOptions())
    for image, expected in [(tag, [1, 2]), (blank, []), (tag, [1, 2]), (blank, [])]:
        assert sorted(d.id for d in detector.detect(image).detections) == expected


def test_independent_native_detectors_can_run_concurrently():
    camera = load_config(DATA / "config.json").camera("front")
    image = next(_recording_frames(DATA / "center.png", camera))

    def detect(_):
        detector = native.CpuDetector(camera.width, camera.height, native.DetectorOptions())
        return [sorted(d.id for d in detector.detect(image).detections) for _ in range(3)]

    with ThreadPoolExecutor(4) as pool:
        assert list(pool.map(detect, range(4))) == [[[1]] * 3] * 4


def test_reset_allows_primary_retry_after_permanent_fallback():
    class Detector:
        failed = True
        calls = 0

        def detect(self, frame):
            self.calls += 1
            if self.failed:
                raise RuntimeError("GPU fault")
            return frame

        def reset(self):
            self.failed = False

    primary, fallback = Detector(), Detector()
    fallback.failed = False
    detector = FallbackDetector(primary, fallback)
    assert detector.detect("first") == "first"
    assert detector.using_fallback
    detector.reset()
    assert not detector.using_fallback
    assert detector.detect("second") == "second"
    assert primary.calls == 2 and fallback.calls == 1


def test_fallback_error_is_visible_to_scheduler():
    class Broken:
        def detect(self, _):
            raise RuntimeError("CPU also failed")

    detector = FallbackDetector(Broken(), Broken())
    with pytest.raises(RuntimeError, match="CPU also failed"):
        detector.detect(None)
    assert detector.using_fallback


@pytest.mark.parametrize("decimate", [1.0, 1.5, 3.0, 4.0])
@pytest.mark.parametrize("fallback", [False, True])
def test_unsupported_cuda_decimation_never_reaches_fatal_native_constructor(
    monkeypatch, decimate, fallback
):
    from spot_vision.native import NativeDetector, create_detector

    camera = load_config(DATA / "config.json").camera("front")
    camera = replace(
        camera,
        detector=replace(
            camera.detector, backend="cuda", decimate=decimate, fallback_to_cpu=fallback
        ),
    )
    monkeypatch.setattr(native, "CUDA_AVAILABLE", True)
    monkeypatch.setattr(
        native, "CudaDetector", lambda *_: pytest.fail("fatal constructor reached"), raising=False
    )
    if fallback:
        result = create_detector(camera, None)
        assert isinstance(result, NativeDetector)
        assert isinstance(result.implementation, native.CpuDetector)
    else:
        with pytest.raises(RuntimeError, match="requires decimate=2"):
            create_detector(camera, None)
