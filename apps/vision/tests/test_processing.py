import json
from types import SimpleNamespace

import pytest

from spot_vision.config import CameraConfig, CameraSelector, ConfigError, DetectorConfig
from spot_vision.processing import CameraDetector, ProcessingBudget, ProcessingPolicy
from spot_vision.protocol import restore


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
        0,
        DetectorConfig(backend=backend),
    )


def test_failed_frames_back_off():
    now = [0.0]
    camera = camera_config()

    def fail(_):
        raise RuntimeError("native failure")

    def factory(*_):
        return SimpleNamespace(detect=fail, reset=lambda: None)

    detector = CameraDetector(camera, None, factory, clock=lambda: now[0])
    with pytest.raises(RuntimeError, match="native failure"):
        detector.detect(None)
    assert detector.backend == "cuda" and not detector.ready(0.9) and detector.ready(1)
    with pytest.raises(RuntimeError):
        CameraDetector(camera, None, lambda *_: fail(None))


def test_common_processing_budget_preserves_fairness():
    policy = ProcessingPolicy()
    cameras = {name: SimpleNamespace(camera=camera_config(name)) for name in ("a", "b", "c", "d")}
    budget = ProcessingBudget(policy)
    for name in cameras:
        budget.completed(name, 0, 0.05)
    budget.update(cameras)
    assert budget.overloaded
    assert len(set(budget.targets.values())) == 1
    assert sum(budget.costs[key] * fps for key, fps in budget.targets.items()) == pytest.approx(0.8)
    assert all(budget.due(key, 1) for key in cameras)
    budget.costs = {}
    budget.update(cameras)
    assert not budget.overloaded and budget.targets["a"] == 30


@pytest.mark.parametrize(
    "value",
    [
        {"max_fps": float("nan")},
        {"utilization_budget": 1},
        {"fallback_to_cpu": False},
    ],
)
def test_invalid_processing_policy_rejected(value):
    with pytest.raises(ConfigError):
        restore(ProcessingPolicy, json.dumps(value))
