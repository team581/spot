from __future__ import annotations

from threading import Event, Lock

from .models import FramePacket


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
