"""Bounded buffering, wakeups, and shutdown under producer/consumer contention."""

import threading

from spot_vision.queues import LatestFrameSlot


def test_slot_wakes_scheduler_and_discards_pending_frame_on_close():
    wake = threading.Event()
    slot = LatestFrameSlot(wake)
    first, second = object(), object()
    assert not slot.put(first)
    assert wake.is_set()
    wake.clear()
    assert slot.put(second)
    assert slot.take() is second
    assert slot.take() is None
    slot.put(first)
    wake.clear()
    slot.close()
    assert wake.is_set()
    assert slot.take() is None
    assert not slot.put(second)
    assert slot.take() is None
