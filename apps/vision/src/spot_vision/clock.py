from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


def wall_time_available() -> bool:
    """Only trust wall time after synchronization, not a plausible RTC date."""
    try:
        return Path("/run/systemd/timesync/synchronized").exists() and time.time() > 1704067200
    except OSError:
        return False


class FrameRateCounter:
    """Count frame intervals over at least one second, including gaps.

    Averaging inverse per-frame intervals overstates throughput when USB reads
    or detector completions arrive in bursts. Each update here uses the total
    number of completed intervals divided by their total elapsed time.
    """

    def __init__(self) -> None:
        self._started: float | None = None
        self._intervals = 0
        self.fps = 0.0

    def update(self, now: float) -> float:
        if self._started is None:
            self._started = now
            return self.fps
        self._intervals += 1
        elapsed = now - self._started
        if elapsed >= 1.0:
            self.fps = self._intervals / elapsed
            self._started = now
            self._intervals = 0
        return self.fps


def nt_now_us() -> int:
    """Return local NT time (NOT proof of synchronization).

    The monotonic fallback is for offline capture/replay only. Spot's
    transport waits for NTCore's server clock offset before publishing.
    """
    try:
        import ntcore

        return int(ntcore._now())  # WPILib's local NT timestamp, in microseconds.
    except (ImportError, AttributeError):
        return time.monotonic_ns() // 1_000


@dataclass(frozen=True)
class SyncSnapshot:
    state: str
    offset_us: int | None


class NtClock:
    """Use NTCore's connection-specific clock offset directly."""

    def __init__(self, instance) -> None:
        self.instance = instance

    def snapshot(self) -> SyncSnapshot:
        offset = self.instance.getServerTimeOffset() if self.instance.isConnected() else None
        return SyncSnapshot("Synchronized" if offset is not None else "Waiting", offset)
