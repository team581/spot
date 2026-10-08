import ctypes as ct
import errno
from types import SimpleNamespace

import pytest

from spot_vision import v4l2_capture as module


def capture(monkeypatch, packets):
    source = module.MjpegCapture.__new__(module.MjpegCapture)
    source.fd, source.timeout, source.streaming = 9, .1, True
    source.buffers = [b'\xff\xd8first\xff\xd9', b'\xff\xd8latest\xff\xd9']
    operations = []
    queue = list(packets)

    def ioctl(fd, number, buffer, direction=3):
        assert fd == 9
        if number == 17:
            if not queue:
                raise BlockingIOError(errno.EAGAIN, 'no frame')
            index, flags = queue.pop(0)
            buffer.index, buffer.flags = index, flags
            buffer.bytesused = len(source.buffers[index])
            operations.append(('dequeue', index))
        else:
            assert number == 15
            operations.append(('requeue', buffer.index))

    def decode(data, mode):
        operations.append(('decode', data.tobytes()))
        return data.tobytes()

    source.cv2 = SimpleNamespace(imdecode=decode, IMREAD_COLOR=1)
    monkeypatch.setattr(module, '_ioctl', ioctl)
    monkeypatch.setattr(module.select, 'select', lambda *_: ([9], [], []) if queue else ([], [], []))
    return source, operations


def test_requeues_every_buffer_before_decoding_only_latest(monkeypatch):
    source, operations = capture(monkeypatch, [(0, 0), (1, 0)])
    assert source.read() == (True, source.buffers[1])
    assert operations == [('dequeue', 0), ('requeue', 0), ('dequeue', 1),
                          ('requeue', 1), ('decode', source.buffers[1])]


def test_error_flag_and_truncated_jpeg_are_requeued_without_decode(monkeypatch):
    source, operations = capture(monkeypatch, [(0, 0x40), (1, 0)])
    source.buffers[1] = b'\xff\xd8truncated'
    assert source.read() == (False, None)
    assert operations == [('dequeue', 0), ('requeue', 0), ('dequeue', 1), ('requeue', 1)]


def test_no_usb_frames_returns_failure_for_reconnect(monkeypatch):
    source, operations = capture(monkeypatch, [])
    assert source.read() == (False, None)
    assert not operations


def test_repeated_driver_io_errors_cannot_hide_stall(monkeypatch):
    source, operations = capture(monkeypatch, [(0, 0)])
    clock = iter([0, 0, 0, .2])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(clock))
    def failure(*_):
        raise OSError(errno.EIO, 'USB error')
    monkeypatch.setattr(module, '_ioctl', failure)
    assert source.read() == (False, None)
    assert not operations


def test_unrecoverable_driver_error_propagates(monkeypatch):
    source, _ = capture(monkeypatch, [(0, 0)])
    def failure(*_):
        raise OSError(errno.ENODEV, 'unplugged')
    monkeypatch.setattr(module, '_ioctl', failure)
    with pytest.raises(OSError, match='unplugged'):
        source.read()


def test_failed_setup_closes_device(monkeypatch):
    monkeypatch.setattr(module.os, 'open', lambda *_: 9)
    closed = []
    monkeypatch.setattr(module.os, 'close', closed.append)
    def ioctl(fd, number, value, direction=3):
        if number == 8:
            value.count = 1
    monkeypatch.setattr(module, '_ioctl', ioctl)
    with pytest.raises(RuntimeError, match='two USB buffers'):
        module.MjpegCapture(None, SimpleNamespace(width=640, height=480, fps=120), '/dev/test')
    assert closed == [9]


def test_linux_64_bit_ioctl_layouts_match_videodev2_header():
    if ct.sizeof(ct.c_void_p) != 8:
        pytest.skip('64-bit ABI check')
    assert ct.sizeof(module._Buffer) == 88
    assert ct.sizeof(module._Format) == 208
    assert ct.sizeof(module._Parameters) == 204
    assert ct.sizeof(module._RequestBuffers) == 20
    assert module._request(17, module._Buffer) == 0xc0585611


def test_bounded_yuyv_capture_removes_driver_padding_and_owns_snapshot(monkeypatch):
    import numpy as np
    source, operations = capture(monkeypatch, [(0,0)])
    source.pixel_format,source.width,source.height,source.bytes_per_line = "YUYV",2,2,6
    source.buffers[0] = bytes([1,2,3,4,99,99,5,6,7,8,99,99])
    ok, image = source.read()
    assert ok and image.flags.c_contiguous and image.flags.owndata
    assert image.shape == (2,2,2)
    assert np.array_equal(image.reshape(-1),[1,2,3,4,5,6,7,8])
    assert operations == [("dequeue",0),("requeue",0)]
