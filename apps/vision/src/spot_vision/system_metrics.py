"""Low-rate OS diagnostics; missing sensors remain unavailable."""

from __future__ import annotations

import math
from pathlib import Path

from .health import jetson_temperature_c


class SystemMetrics:
    def __init__(self) -> None:
        self.previous = None
        self.snapshot = {
            "cpu_percent": None,
            "gpu_percent": None,
            "memory_used_gb": None,
            "memory_total_gb": None,
            "temperature_c": None,
        }

    def update(self) -> dict:
        result = self.snapshot.copy()
        try:
            values = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(values), values[3] + values[4]
            if self.previous and total > self.previous[0]:
                result["cpu_percent"] = 100 * (
                    1 - (idle - self.previous[1]) / (total - self.previous[0])
                )
            self.previous = total, idle
            memory = {
                line.split(":")[0]: int(line.split()[1]) * 1024
                for line in Path("/proc/meminfo").read_text().splitlines()
            }
            result["memory_total_gb"] = memory["MemTotal"] / 1e9
            result["memory_used_gb"] = (memory["MemTotal"] - memory["MemAvailable"]) / 1e9
        except (OSError, ValueError, KeyError, IndexError):
            pass
        temperature = jetson_temperature_c()
        result["temperature_c"] = temperature if math.isfinite(temperature) else None
        for candidate in list(Path("/sys/class/devfreq").glob("*gpu*/load")) + list(
            Path("/sys/devices/platform").glob("*ga10b/load")
        ):
            try:
                value = int(candidate.read_text()) / 10
                if 0 <= value <= 100:
                    result["gpu_percent"] = value
                    break
            except (OSError, ValueError):
                continue
        self.snapshot = result
        return result
