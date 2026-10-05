"""Bounded buffering, wakeups, and shutdown under producer/consumer contention."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from spot_vision.queues import BoundedDropOldestQueue, LatestFrameSlot


@pytest.mark.parametrize("capacity", [0, -1, -20])
def test_queue_rejects_nonpositive_capacity(capacity):
    with pytest.raises(ValueError, match="positive"):
        BoundedDropOldestQueue(capacity)


@pytest.mark.parametrize("capacity", [1, 2, 7])
def test_overload_retains_only_newest_items(capacity):
    queue = BoundedDropOldestQueue(capacity)
    dropped = [queue.put(i) for i in range(100)]
    assert sum(dropped) == 100 - capacity
    assert len(queue) == capacity
    assert [queue.get() for _ in range(capacity)] == list(range(100 - capacity, 100))
    assert queue.get(timeout=0) is None


def test_closed_queue_drains_pending_items_and_rejects_new_writes():
    queue = BoundedDropOldestQueue(2)
    queue.put(1)
    queue.close()
    queue.close()
    assert not queue.put(2)
    assert queue.get() == 1
    assert queue.get() is None
    assert len(queue) == 0


def test_close_releases_all_blocked_consumers():
    queue = BoundedDropOldestQueue(2)
    entered = threading.Barrier(5)

    def consume():
        entered.wait(timeout=2)
        return queue.get()

    with ThreadPoolExecutor(4) as pool:
        waiting = [pool.submit(consume) for _ in range(4)]
        try:
            entered.wait(timeout=2)
        finally:
            queue.close()
        assert [future.result(timeout=2) for future in waiting] == [None] * 4


def test_put_wakes_waiting_consumer():
    queue = BoundedDropOldestQueue(1)
    with ThreadPoolExecutor(1) as pool:
        waiting = pool.submit(queue.get, 2)
        queue.put(42)
        assert waiting.result(timeout=3) == 42
    queue.close()


def test_concurrent_producers_do_not_exceed_capacity_or_duplicate_items():
    queue = BoundedDropOldestQueue(17)
    with ThreadPoolExecutor(4) as pool:
        futures = [pool.submit(lambda start=start: [queue.put((start, i)) for i in range(200)])
                   for start in range(4)]
        drops = sum(sum(future.result(timeout=3)) for future in futures)
    assert drops == 800 - 17
    queue.close()
    retained = [queue.get() for _ in range(17)]
    assert len(set(retained)) == 17
    assert queue.get() is None


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
