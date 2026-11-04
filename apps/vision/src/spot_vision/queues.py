from __future__ import annotations

from collections import deque
from threading import Condition, Event, Lock
from typing import Generic, Protocol, TypeVar

from .models import DetectedFrame, FramePacket

T = TypeVar("T")


class Framed(Protocol):
    @property
    def frame(self) -> FramePacket: ...


F = TypeVar("F", bound=Framed)


class ResultQueue(Protocol):
    def put(self, item: DetectedFrame) -> bool: ...
    def get(self, timeout: float | None = None) -> DetectedFrame | None: ...


class LatestFrameSlot:
    def __init__(self, wake_event: Event | None = None) -> None:
        self._lock = Lock()
        self._frame: FramePacket | None = None
        self._closed = False
        self._wake_event = wake_event

    def put(self, frame: FramePacket) -> bool:
        """Store a frame and return True if an older pending frame was replaced."""
        with self._lock:
            if self._closed:
                return False
            replaced = self._frame is not None
            self._frame = frame
        if self._wake_event is not None:
            self._wake_event.set()
        return replaced

    def take(self) -> FramePacket | None:
        with self._lock:
            frame = self._frame
            self._frame = None
            return frame

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._frame = None
        if self._wake_event is not None:
            self._wake_event.set()


class BoundedDropOldestQueue(Generic[T]):
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._items: deque[T] = deque()
        self._condition = Condition()
        self._closed = False

    def put(self, item: T) -> bool:
        """Insert an item and return True when the oldest item was discarded."""
        with self._condition:
            if self._closed:
                return False
            dropped = len(self._items) == self.capacity
            if dropped:
                self._items.popleft()
            self._items.append(item)
            self._condition.notify()
            return dropped

    def get(self, timeout: float | None = None) -> T | None:
        with self._condition:
            if not self._items and not self._closed:
                self._condition.wait(timeout)
            if self._items:
                return self._items.popleft()
            return None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def __len__(self) -> int:
        with self._condition:
            return len(self._items)


class FairResultQueue(Generic[F]):
    """Bounded per-camera queues and round-robin delivery.

    A fast producer can replace only its own results. Offline cameras never
    delay delivery; the capacity argument is per camera.
    """

    def __init__(self, camera_ids: list[str], capacity: int) -> None:
        if capacity < 1 or len(set(camera_ids)) != len(camera_ids):
            raise ValueError("positive capacity and unique camera IDs required")
        self.capacity = capacity
        self._ids = tuple(camera_ids)
        self._queues: dict[str, deque[F]] = {key: deque() for key in camera_ids}
        self._condition = Condition()
        self._cursor = 0
        self._closed = False

    def put(self, item: F) -> bool:
        with self._condition:
            if self._closed:
                return False
            queue = self._queues[item.frame.camera_id]
            dropped = len(queue) == self.capacity
            if dropped:
                queue.popleft()
            queue.append(item)
            self._condition.notify()
            return dropped

    def get(self, timeout: float | None = None) -> F | None:
        with self._condition:
            if not any(self._queues.values()) and not self._closed:
                self._condition.wait(timeout)
            for offset in range(len(self._ids)):
                index = (self._cursor + offset) % len(self._ids)
                queue = self._queues[self._ids[index]]
                if queue:
                    self._cursor = (index + 1) % len(self._ids)
                    return queue.popleft()
            return None

    def clear(self) -> None:
        with self._condition:
            for queue in self._queues.values():
                queue.clear()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def __len__(self) -> int:
        with self._condition:
            return sum(len(queue) for queue in self._queues.values())
