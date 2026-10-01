from __future__ import annotations

import time


def nt_now_us() -> int:
    """Return NT synchronized time when NTCore is available, monotonic time otherwise."""
    try:
        import ntcore

        return int(ntcore._now())  # WPILib's local NT timestamp, in microseconds.
    except (ImportError, AttributeError):
        return time.monotonic_ns() // 1_000
