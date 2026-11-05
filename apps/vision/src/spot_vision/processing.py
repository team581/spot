"""Fair processing budgets; never change optical modes."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace

from .config import ConfigError
from .configuration import TagSelection
from .models import PoseSolution


@dataclass(frozen=True)
class ProcessingPolicy:
    max_fps: float = 30
    utilization_budget: float = 0.8

    @classmethod
    def parse(cls, values: dict | None):
        if values is not None and not isinstance(values, dict):
            raise ConfigError("Processing policy must be an object")
        try:
            policy = cls(**(values or {}))
        except TypeError as exc:
            raise ConfigError("Unknown processing policy field") from exc
        for key, low, high in (("max_fps", 1, 120), ("utilization_budget", 0.1, 0.95)):
            value = getattr(policy, key)
            if (
                type(value) not in (float, int)
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ConfigError(f"Invalid processing policy {key}")
        return policy


class CameraDetector:
    """Run one camera's configured backend, pausing for a second after a failure."""

    def __init__(self, camera, calibration, factory, *, clock=time.monotonic):
        self.camera = camera
        self.clock = clock
        self.backend = camera.detector.backend
        self.blocked_until = 0.0
        self.detector = factory(camera, calibration)

    def ready(self, now):
        return now >= self.blocked_until

    def detect(self, image):
        try:
            return self.detector.detect(image)
        except Exception:
            self.blocked_until = self.clock() + 1
            raise

    def snapshot(self):
        return {"backend": self.backend}


class ProcessingBudget:
    def __init__(self, policy: ProcessingPolicy):
        self.policy = policy
        self.costs, self.last, self.targets = {}, {}, {}
        self.overloaded = False

    def update(self, detectors):
        self.costs = {key: value for key, value in self.costs.items() if key in detectors}
        self.last = {key: value for key, value in self.last.items() if key in detectors}
        targets = {
            key: min(detector.camera.fps, self.policy.max_fps)
            for key, detector in detectors.items()
        }
        demand = sum(self.costs.get(key, 0) * fps for key, fps in targets.items())
        scale = min(1, self.policy.utilization_budget / demand) if demand > 0 else 1
        self.overloaded = scale < 1
        self.targets = {key: fps * scale for key, fps in targets.items()}

    def due(self, identity, now):
        target = self.targets.get(identity, self.policy.max_fps)
        return now - self.last.get(identity, -math.inf) >= 1 / target

    def completed(self, identity, started, duration):
        self.last[identity] = started
        self.costs[identity] = self.costs.get(identity, duration) * 0.8 + duration * 0.2


def solve_tag_selection(solver, detections, selection: TagSelection | None) -> PoseSolution:
    """Only selected detections reach geometry; exclusions remain diagnostics."""
    allowed = set(selection.allowed_tag_ids) if selection else set()
    selected = tuple(tag for tag in detections if tag.id in allowed)
    solution = solver.solve(selected) if selected else PoseSolution()
    excluded = {tag.id: "tag-policy-excluded" for tag in detections if tag.id not in allowed}
    return replace(solution, rejection_reasons={**solution.rejection_reasons, **excluded})
