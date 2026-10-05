from __future__ import annotations

import time


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
    """Return NT synchronized time when NTCore is available, monotonic time otherwise."""
    try:
        import ntcore

        return int(ntcore._now())  # WPILib's local NT timestamp, in microseconds.
    except (ImportError, AttributeError):
        return time.monotonic_ns() // 1_000
