"""Bounded, latest-only Linux UVC capture with promptly requeued USB buffers."""

from __future__ import annotations

import ctypes as ct
import errno
import fcntl
import mmap
import os
import select
import time

import numpy as np


class _Timeval(ct.Structure):
    _fields_ = [("seconds", ct.c_long), ("microseconds", ct.c_long)]


class _Timecode(ct.Structure):
    _fields_ = [
        ("type", ct.c_uint32),
        ("flags", ct.c_uint32),
        ("frames", ct.c_uint8),
        ("seconds", ct.c_uint8),
        ("minutes", ct.c_uint8),
        ("hours", ct.c_uint8),
        ("userbits", ct.c_uint8 * 4),
    ]


class _BufferMemory(ct.Union):
    _fields_ = [
        ("offset", ct.c_uint32),
        ("userptr", ct.c_ulong),
        ("planes", ct.c_void_p),
        ("fd", ct.c_int32),
    ]


class _Buffer(ct.Structure):
    _fields_ = [
        ("index", ct.c_uint32),
        ("type", ct.c_uint32),
        ("bytesused", ct.c_uint32),
        ("flags", ct.c_uint32),
        ("field", ct.c_uint32),
        ("timestamp", _Timeval),
        ("timecode", _Timecode),
        ("sequence", ct.c_uint32),
        ("memory", ct.c_uint32),
        ("m", _BufferMemory),
        ("length", ct.c_uint32),
        ("reserved2", ct.c_uint32),
        ("request_fd", ct.c_int32),
    ]


class _RequestBuffers(ct.Structure):
    _fields_ = [
        ("count", ct.c_uint32),
        ("type", ct.c_uint32),
        ("memory", ct.c_uint32),
        ("capabilities", ct.c_uint32),
        ("flags", ct.c_uint8),
        ("reserved", ct.c_uint8 * 3),
    ]


class _FormatData(ct.Union):
    _fields_ = [("raw", ct.c_uint32 * 50), ("alignment", ct.c_void_p)]


class _Format(ct.Structure):
    _fields_ = [("type", ct.c_uint32), ("data", _FormatData)]


class _Parameters(ct.Structure):
    _fields_ = [("type", ct.c_uint32), ("data", ct.c_uint32 * 50)]


def _request(number, structure, direction=3):
    return (direction << 30) | (ct.sizeof(structure) << 16) | (ord("V") << 8) | number


def _ioctl(fd, number, value, direction=3):
    data = bytearray(bytes(value))
    fcntl.ioctl(fd, _request(number, type(value), direction), data, True)
    ct.memmove(ct.addressof(value), bytes(data), len(data))


def _buffer(index=0):
    return _Buffer(index=index, type=1, memory=1)  # VIDEO_CAPTURE, MMAP


class V4l2Capture:
    """OpenCV-compatible read/release interface; no hidden, unbounded read loop."""

    def __init__(self, cv2, camera, device: str, timeout: float = 1.0) -> None:
        self.cv2 = cv2
        self.timeout = timeout
        self.width, self.height = camera.width, camera.height
        requested_format = getattr(camera, "format", "MJPG").upper()
        self.pixel_format = "MJPG" if requested_format in ("MJPG", "MJPEG") else "YUYV"
        if requested_format not in ("MJPG", "MJPEG", "YUYV", "YUY2"):
            raise ValueError("bounded capture supports MJPEG and YUYV")
        self.bytes_per_line = self.width * 2
        self.negotiated_fps = None
        self.last_sequence = None
        self.fd = -1
        self.buffers = []
        self.streaming = False
        try:
            self.fd = os.open(device, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
            fmt = _Format(type=1)
            fmt.data.raw[0:4] = (
                camera.width,
                camera.height,
                int.from_bytes(self.pixel_format.encode(), "little"),
                0,
            )
            _ioctl(self.fd, 5, fmt)  # S_FMT
            if tuple(fmt.data.raw[:3]) != (
                camera.width,
                camera.height,
                int.from_bytes(self.pixel_format.encode(), "little"),
            ):
                raise RuntimeError("camera did not accept the configured image mode")
            if self.pixel_format == "YUYV":
                self.bytes_per_line = int(fmt.data.raw[4]) or self.width * 2
                if self.bytes_per_line < self.width * 2:
                    raise RuntimeError("driver returned a truncated packed YUYV row")
            params = _Parameters(type=1)
            params.data[2:4] = (1, camera.fps)  # timeperframe numerator/denominator
            _ioctl(self.fd, 22, params)  # S_PARM
            actual_params = _Parameters(type=1)
            _ioctl(self.fd, 21, actual_params)  # G_PARM; requested S_PARM is not readback
            params = actual_params
            if params.data[2] and params.data[3]:
                self.negotiated_fps = float(params.data[3]) / float(params.data[2])
            request = _RequestBuffers(count=4, type=1, memory=1)
            _ioctl(self.fd, 8, request)  # REQBUFS
            if request.count < 2:
                raise RuntimeError("MJPEG capture needs at least two USB buffers")
            for index in range(request.count):
                buffer = _buffer(index)
                _ioctl(self.fd, 9, buffer)  # QUERYBUF
                self.buffers.append(
                    mmap.mmap(
                        self.fd,
                        buffer.length,
                        flags=mmap.MAP_SHARED,
                        prot=mmap.PROT_READ | mmap.PROT_WRITE,
                        offset=buffer.m.offset,
                    )
                )
                _ioctl(self.fd, 15, buffer)  # QBUF
            _ioctl(self.fd, 18, ct.c_uint32(1), direction=1)  # STREAMON
            self.streaming = True
        except Exception:
            self.release()
            raise

    def read(self):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            remaining = max(0, deadline - time.monotonic())
            try:
                ready, _, _ = select.select([self.fd], [], [], remaining)
            except InterruptedError:
                continue
            if not ready:
                return False, None
            latest = None
            sequence = None
            # Bounded draining keeps latency low without chasing arriving frames
            # forever. Requeue before decoding so USB never waits on image work.
            for _ in range(len(self.buffers)):
                buffer = _buffer()
                try:
                    _ioctl(self.fd, 17, buffer)  # DQBUF
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EINTR, errno.EIO):
                        break
                    raise
                try:
                    if buffer.index >= len(self.buffers):
                        raise RuntimeError("camera returned an invalid USB buffer index")
                    storage = self.buffers[buffer.index]
                    if not buffer.flags & 0x40 and 0 < buffer.bytesused <= len(storage):
                        data = storage[: buffer.bytesused]
                        if (
                            getattr(self, "pixel_format", "MJPG") == "MJPG"
                            and data.startswith(b"\xff\xd8")
                            and data.endswith(b"\xff\xd9")
                        ) or (
                            getattr(self, "pixel_format", "MJPG") == "YUYV"
                            and len(data) >= self.bytes_per_line * self.height
                        ):
                            latest = data
                            sequence = buffer.sequence
                finally:
                    _ioctl(self.fd, 15, buffer)  # QBUF, including damaged frames
            if latest is not None:
                if getattr(self, "pixel_format", "MJPG") == "YUYV":
                    image = np.frombuffer(
                        latest, dtype=np.uint8, count=self.bytes_per_line * self.height
                    ).reshape(self.height, self.bytes_per_line)
                    image = image[:, : self.width * 2].reshape(self.height, self.width, 2).copy()
                else:
                    image = self.cv2.imdecode(
                        np.frombuffer(latest, dtype=np.uint8), self.cv2.IMREAD_GRAYSCALE
                    )
                if image is not None:
                    assert sequence is not None
                    self.last_sequence = sequence
                    return True, image
        return False, None

    def release(self) -> None:
        if self.fd < 0:
            return
        try:
            if self.streaming:
                try:
                    _ioctl(self.fd, 19, ct.c_uint32(1), direction=1)  # STREAMOFF
                except OSError:
                    pass
            for storage in self.buffers:
                storage.close()
        finally:
            self.buffers.clear()
            os.close(self.fd)
            self.fd = -1
            self.streaming = False
