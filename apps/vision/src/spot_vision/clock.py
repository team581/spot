from __future__ import annotations

import threading
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

    The monotonic fallback is for offline alpha capture/replay only. Spot's
    transport requires NTCore and a verified ClockGate before publishing.
    """
    try:
        import ntcore

        return int(ntcore._now())  # WPILib's local NT timestamp, in microseconds.
    except (ImportError, AttributeError):
        return time.monotonic_ns() // 1_000


@dataclass(frozen=True)
class SyncSnapshot:
    state: str
    connection_epoch: int
    sync_epoch: int
    offset_us: int | None
    update_age_s: float | None
    ready_since_ns: int
    discontinuities: int


class ClockGate:
    """Connection-specific NT4 synchronization, driven by actual sync events.

    Limits are engineering defaults requiring real-roboRIO qualification.
    Offset magnitude is deliberately unrestricted across independent boots.
    No wall time or guessed latency participates in this state machine.
    """

    def __init__(
        self, *, expiry_s: float = 30.0, jump_us: int = 5_000, max_rtt2_us: int = 5_000
    ) -> None:
        if expiry_s <= 0 or jump_us <= 0 or max_rtt2_us <= 0:
            raise ValueError("clock limits must be positive")
        self.expiry_s, self.jump_us, self.max_rtt2_us = expiry_s, jump_us, max_rtt2_us
        self._lock = threading.RLock()
        self._connection: str | None = None
        self._connection_epoch = self._sync_epoch = self._discontinuities = 0
        self._state = "Waiting"
        self._offset: int | None = None
        self._updated_ns: int | None = None
        self._ready_ns = 0

    def connection(self, token: str | None) -> None:
        with self._lock:
            if token == self._connection:
                return
            self._connection = token
            self._connection_epoch += 1
            self._invalidate("Waiting")
            self._offset = None
            self._updated_ns = None

    def _invalidate(self, state: str) -> None:
        self._state = state
        self._sync_epoch += 1
        self._ready_ns = 0

    def update(
        self, offset_us: int | None, rtt2_us: int, valid: bool, now_ns: int | None = None
    ) -> None:
        now = time.monotonic_ns() if now_ns is None else now_ns
        with self._lock:
            self._expire(now)
            if self._connection is None:
                return
            if not valid or offset_us is None or not 0 <= rtt2_us <= self.max_rtt2_us:
                if self._state != "Invalid":
                    self._invalidate("Invalid")
                self._offset = None
                self._updated_ns = None
                return
            if self._offset is not None and abs(offset_us - self._offset) > self.jump_us:
                self._discontinuities += 1
                self._invalidate("Invalid")
                # This sample establishes a new baseline; a subsequent exchange
                # is required before accepting newly captured frames.
                self._offset, self._updated_ns = offset_us, now
                return
            self._offset, self._updated_ns = offset_us, now
            if self._state != "Synchronized":
                self._sync_epoch += 1
                self._state = "Synchronized"
                self._ready_ns = now

    def _expire(self, now: int) -> None:
        if (
            self._state == "Synchronized"
            and self._updated_ns is not None
            and (now - self._updated_ns) / 1e9 > self.expiry_s
        ):
            self._invalidate("Waiting")
            self._offset = None

    def invalidate_jump(self) -> None:
        with self._lock:
            self._discontinuities += 1
            self._invalidate("Invalid")
            self._offset = None
            self._updated_ns = None

    def snapshot(self, now_ns: int | None = None) -> SyncSnapshot:
        now = time.monotonic_ns() if now_ns is None else now_ns
        with self._lock:
            self._expire(now)
            return SyncSnapshot(
                self._state,
                self._connection_epoch,
                self._sync_epoch,
                self._offset,
                None if self._updated_ns is None else (now - self._updated_ns) / 1e9,
                self._ready_ns,
                self._discontinuities,
            )
