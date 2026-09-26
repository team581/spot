from __future__ import annotations

import glob
from pathlib import Path


def jetson_temperature_c() -> float:
    readings: list[float] = []
    for path_text in glob.glob("/sys/devices/virtual/thermal/thermal_zone*/temp"):
        try:
            raw = float(Path(path_text).read_text().strip())
            readings.append(raw / 1000.0 if raw > 500 else raw)
        # Some Jetson thermal-zone drivers can transiently return malformed
        # data while a sensor is being refreshed. Temperature telemetry must
        # not be able to terminate the vision output worker.
        except (OSError, TypeError, ValueError):
            continue
    return max(readings, default=float("nan"))


class Watchdog:
    def __init__(self) -> None:
        try:
            import sdnotify

            self._notifier = sdnotify.SystemdNotifier()
        except ImportError:
            self._notifier = None

    def ready(self) -> None:
        if self._notifier:
            self._notifier.notify("READY=1")

    def ping(self, status: str = "Buddy Vision running") -> None:
        if self._notifier:
            self._notifier.notify(f"WATCHDOG=1\nSTATUS={status}")

    def stopping(self) -> None:
        if self._notifier:
            self._notifier.notify("STOPPING=1")
