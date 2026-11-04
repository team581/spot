from types import SimpleNamespace

import pytest

from spot_vision.config import CameraConfig, CameraSelector, ConfigError, DetectorConfig
from spot_vision.processing import ProcessingBudget, ProcessingPolicy, RecoveringDetector


def camera_config(name="front", backend="cuda"):
    return CameraConfig(
        name,
        True,
        CameraSelector(),
        "MJPG",
        640,
        480,
        30,
        None,
        None,
        False,
        None,
        0,
        1,
        DetectorConfig(backend=backend),
    )


def test_explicit_fallback_and_bounded_recovery_never_duplicate_exposure():
    now, calls = [0.0], []
    fail = [True]

    def factory(camera, _):
        def detect(image):
            calls.append((camera.detector.backend, image))
            if camera.detector.backend == "cuda" and fail[0]:
                raise RuntimeError("Recoverable GPU failure")
            return image

        return SimpleNamespace(detect=detect, reset=lambda: None)

    camera = camera_config()
    policy = ProcessingPolicy.parse(
        {"fallback_to_cpu": True, "gpu_retry_s": 5, "gpu_max_retries": 2}
    )
    detector = RecoveringDetector(camera, None, factory, policy, clock=lambda: now[0])
    original = detector.generation
    assert detector.detect("frame-1") == "frame-1"
    degraded = detector.generation
    assert detector.backend == "cpu" and degraded != original
    for i in range(5):
        now[0] = i * 0.1
        detector.detect("cpu-frame")
    assert sum(backend == "cuda" for backend, _ in calls) == 1
    now[0] = 5
    detector.detect("probe-fails")
    assert detector.retries == 1 and detector.generation == degraded
    fail[0], now[0] = False, 10
    assert detector.detect("probe-passes") == "probe-passes"
    assert calls[-1] == ("cuda", "probe-passes")
    assert sum(frame == "probe-passes" for _, frame in calls) == 1
    assert detector.backend == "cuda" and detector.generation != degraded
    fail[0] = True
    detector.detect("fails-again")
    now[0] = 100
    detector.detect("budget-exhausted")
    assert detector.retries == 2


def test_strict_cuda_failure_and_failed_cpu_frames_back_off():
    now = [0.0]
    camera = camera_config()

    def fail(_):
        raise RuntimeError("native failure")

    def factory(*_):
        return SimpleNamespace(detect=fail, reset=lambda: None)

    detector = RecoveringDetector(camera, None, factory, ProcessingPolicy(), clock=lambda: now[0])
    with pytest.raises(RuntimeError, match="native failure"):
        detector.detect(None)
    assert detector.backend == "cuda" and not detector.ready(0.9) and detector.ready(1)
    with pytest.raises(RuntimeError):
        RecoveringDetector(camera, None, lambda *_: fail(None), ProcessingPolicy())


def test_common_processing_budget_preserves_fairness_and_thermal_hysteresis():
    policy = ProcessingPolicy()
    cameras = {
        name: SimpleNamespace(camera=camera_config(name), snapshot=lambda: {"degraded": False})
        for name in ("a", "b", "c", "d")
    }
    budget = ProcessingBudget(policy)
    for name in cameras:
        budget.completed(name, 0, 0.05)
    budget.update(cameras, 40)
    assert budget.overloaded
    assert len(set(budget.targets.values())) == 1
    assert sum(budget.costs[key] * fps for key, fps in budget.targets.items()) == pytest.approx(0.8)
    assert all(budget.due(key, 1) for key in cameras)
    budget.costs = {}
    budget.update(cameras, 81)
    assert budget.thermal and budget.targets["a"] == 10
    budget.update(cameras, 77)
    assert budget.thermal
    budget.update(cameras, 74)
    assert not budget.thermal and budget.targets["a"] == 30


@pytest.mark.parametrize(
    "value",
    [
        {"fallback_to_cpu": 1},
        {"gpu_retry_s": 0},
        {"max_fps": float("nan")},
        {"gpu_max_retries": -1},
        {"thermal_exit_c": 90},
        {"unknown": True},
    ],
)
def test_invalid_processing_policy_rejected(value):
    with pytest.raises(ConfigError):
        ProcessingPolicy.parse(value)
