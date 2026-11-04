"""Explicit detector recovery and fair processing budgets; never change optical modes."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, replace

from .config import ConfigError
from .configuration import TagSelection
from .models import PoseSolution


@dataclass(frozen=True)
class ProcessingPolicy:
    fallback_to_cpu: bool = False
    max_fps: float = 30
    degraded_fps: float = 5
    thermal_fps: float = 10
    thermal_enter_c: float = 80
    thermal_exit_c: float = 75
    gpu_retry_s: float = 30
    gpu_max_retries: int = 3
    utilization_budget: float = 0.8

    @classmethod
    def parse(cls, values: dict | None):
        if values is not None and not isinstance(values, dict):
            raise ConfigError("Processing policy must be an object")
        try:
            policy = cls(**(values or {}))
        except TypeError as exc:
            raise ConfigError("Unknown processing policy field") from exc
        if type(policy.fallback_to_cpu) is not bool:
            raise ConfigError("CPU fallback must be explicitly true or false")
        for key, low, high in (
            ("max_fps", 1, 120),
            ("degraded_fps", 1, 30),
            ("thermal_fps", 1, 30),
            ("thermal_enter_c", 50, 100),
            ("thermal_exit_c", 40, 99),
            ("gpu_retry_s", 5, 300),
            ("utilization_budget", 0.1, 0.95),
        ):
            value = getattr(policy, key)
            if (
                type(value) not in (float, int)
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ConfigError(f"Invalid processing policy {key}")
        if (
            type(policy.gpu_max_retries) is not int
            or not 0 <= policy.gpu_max_retries <= 10
            or policy.thermal_exit_c >= policy.thermal_enter_c
            or max(policy.degraded_fps, policy.thermal_fps) > policy.max_fps
        ):
            raise ConfigError("Invalid processing recovery limits")
        return policy


class RecoveringDetector:
    def __init__(
        self, camera, calibration, factory, policy: ProcessingPolicy, *, clock=time.monotonic
    ):
        self.camera, self.calibration, self.factory, self.policy = (
            camera,
            calibration,
            factory,
            policy,
        )
        self.clock = clock
        self.backend = camera.detector.backend
        self.generation = uuid.uuid4().hex
        self.retries, self.next_attempt, self.error = 0, 0.0, ""
        self.blocked_until = 0.0
        self.primary, self.cpu = None, None
        # The alpha factory's permanent fallback is deliberately disabled here.
        self.camera = replace(camera, detector=replace(camera.detector, fallback_to_cpu=False))
        try:
            self.primary = factory(self.camera, calibration)
        except Exception as exc:
            if self.backend != "cuda" or not policy.fallback_to_cpu:
                raise
            self._fallback(exc)

    def _fallback(self, error):
        if self.cpu is None:
            cpu_camera = replace(self.camera, detector=replace(self.camera.detector, backend="cpu"))
            self.cpu = self.factory(cpu_camera, self.calibration)
        self.backend, self.error = "cpu", str(error)[:512]
        self.generation = uuid.uuid4().hex
        self.next_attempt = self.clock() + self.policy.gpu_retry_s

    def ready(self, now):
        # CPU recovery probes have a separate deadline from CPU frame processing.
        return now >= self.blocked_until

    def detect(self, image):
        now = self.clock()
        if (
            self.backend == "cpu"
            and self.camera.detector.backend == "cuda"
            and now >= self.next_attempt
            and self.retries < self.policy.gpu_max_retries
        ):
            self.retries += 1
            self.next_attempt = now + self.policy.gpu_retry_s
            try:
                if self.primary is None:
                    self.primary = self.factory(self.camera, self.calibration)
                else:
                    self.primary.reset()
                result = self.primary.detect(image)
                self.backend, self.error = "cuda", ""
                self.generation = uuid.uuid4().hex
                return result  # Never detect/fuse this exposure a second time.
            except Exception as exc:  # noqa: BLE001 - recoverable native boundary
                self.error = str(exc)[:512]
        if self.backend == "cpu" and self.cpu is not None:
            try:
                return self.cpu.detect(image)
            except Exception:
                self.blocked_until = now + 1
                raise
        try:
            assert self.primary is not None
            result = self.primary.detect(image)
            self.error = ""
            return result
        except Exception as exc:
            if self.backend == "cuda" and self.policy.fallback_to_cpu:
                self._fallback(exc)
                try:
                    assert self.cpu is not None
                    return self.cpu.detect(image)
                except Exception:
                    self.blocked_until = now + 1
                    raise
            self.blocked_until = now + 1
            raise

    def snapshot(self):
        return {
            "backend": self.backend,
            "backend_generation": self.generation,
            "degraded": self.backend != self.camera.detector.backend,
            "gpu_retries": self.retries,
            "backend_error": self.error,
        }


class ProcessingBudget:
    def __init__(self, policy: ProcessingPolicy):
        self.policy = policy
        self.costs, self.last, self.targets = {}, {}, {}
        self.thermal, self.overloaded = False, False

    def update(self, detectors, temperature):
        self.costs = {key: value for key, value in self.costs.items() if key in detectors}
        self.last = {key: value for key, value in self.last.items() if key in detectors}
        if temperature is not None and math.isfinite(temperature):
            if temperature >= self.policy.thermal_enter_c:
                self.thermal = True
            elif temperature <= self.policy.thermal_exit_c:
                self.thermal = False
        targets = {
            key: min(
                detector.camera.fps,
                self.policy.max_fps,
                self.policy.degraded_fps if detector.snapshot()["degraded"] else math.inf,
                self.policy.thermal_fps if self.thermal else math.inf,
            )
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
