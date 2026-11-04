"""Device selection, backend fallback and capture retry regressions."""

import threading
from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from spot_vision import capture
from spot_vision.config import CameraConfig, CameraSelector, DetectorConfig
from spot_vision.models import CameraCounters, CameraState
from spot_vision.queues import LatestFrameSlot


def camera(**changes):
    base = CameraConfig(
        "front",
        True,
        CameraSelector(device="/dev/fake"),
        "YUY2",
        16,
        8,
        60,
        None,
        None,
        False,
        None,
        27,
        1,
        DetectorConfig(backend="cpu"),
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    "selector,expected",
    [
        (CameraSelector(device="/dev/video2"), "/dev/video2"),
        (CameraSelector(by_id="usb-camera"), "/dev/v4l/by-id/usb-camera"),
        (CameraSelector(by_id="/custom/camera"), "/custom/camera"),
        (CameraSelector(by_path="port-camera"), "/dev/v4l/by-path/port-camera"),
        (CameraSelector(by_path="/custom/port"), "/custom/port"),
    ],
)
def test_persistent_selector_resolution(monkeypatch, selector, expected):
    monkeypatch.setattr(capture, "_real_device", lambda path: path)
    assert capture.resolve_device(selector) == expected


def test_device_symlink_resolves_and_missing_device_is_reported(tmp_path):
    device = tmp_path / "device"
    device.touch()
    link = tmp_path / "link"
    link.symlink_to(device)
    assert capture.resolve_device(CameraSelector(device=str(link))) == str(device)
    device.unlink()
    with pytest.raises(capture.CameraError, match="does not exist"):
        capture.resolve_device(CameraSelector(device=str(link)))


@pytest.mark.parametrize("udev", [False, True])
def test_serial_selection_supports_by_id_and_udev_fallback(monkeypatch, udev):
    monkeypatch.setattr(
        capture.glob,
        "glob",
        lambda path: (
            ([] if udev else ["/dev/v4l/by-id/usb-serial581"])
            if "by-id" in path
            else ["/dev/video1", "/dev/video2"]
        ),
    )
    monkeypatch.setattr(capture, "_real_device", lambda path: path)
    monkeypatch.setattr(
        capture.subprocess,
        "run",
        lambda args, **kw: SimpleNamespace(
            stdout="ID_SERIAL_SHORT=serial581\n"
            if args[-1] == "--name=/dev/video2"
            else "OTHER=1\n"
        ),
    )
    assert capture.resolve_device(CameraSelector(serial="serial581")) == (
        "/dev/video2" if udev else "/dev/v4l/by-id/usb-serial581"
    )


def test_missing_serial_and_empty_selector_report_errors(monkeypatch):
    monkeypatch.setattr(capture.glob, "glob", lambda _: [])
    with pytest.raises(capture.CameraError, match="no camera with serial"):
        capture.resolve_device(CameraSelector(serial="absent"))
    with pytest.raises(capture.CameraError, match="selector is empty"):
        capture.resolve_device(CameraSelector())


@pytest.mark.parametrize("mode", ["missing_tool", "driver_error", "success"])
def test_enumeration_error_handling(monkeypatch, mode):
    def run(args, **kwargs):
        assert "--list-formats-ext" in args and kwargs["timeout"] == 10
        if mode == "missing_tool":
            raise FileNotFoundError()
        return SimpleNamespace(
            returncode=int(mode == "driver_error"), stderr="disconnected", stdout="modes"
        )

    monkeypatch.setattr(capture.subprocess, "run", run)
    if mode == "success":
        assert capture.enumerate_camera("/dev/fake") == "modes"
    else:
        with pytest.raises(
            capture.CameraError, match="required" if mode == "missing_tool" else "disconnected"
        ):
            capture.enumerate_camera("/dev/fake")


@pytest.mark.parametrize("opened", [(True, False), (False, True), (False, False)])
def test_backend_fallback_releases_failed_handles_and_requests_bounded_buffers(monkeypatch, opened):
    handles = []

    class Handle:
        def __init__(self, index):
            self.index, self.released, self.properties = index, False, {}

        def isOpened(self):
            return opened[self.index]

        def set(self, key, value):
            self.properties[key] = value

        def release(self):
            self.released = True

    def make(*_):
        handle = Handle(len(handles))
        handles.append(handle)
        return handle

    monkeypatch.setattr(cv2, "VideoCapture", make)
    if not any(opened):
        with pytest.raises(capture.CameraError, match="could not open"):
            capture.open_capture(cv2, camera(), "/dev/fake")
        assert all(handle.released for handle in handles)
    else:
        handle, bgr = capture.open_capture(cv2, camera(), "/dev/fake")
        assert bgr == (not opened[0])
        if bgr:
            assert handles[0].released
            assert handle.properties[cv2.CAP_PROP_BUFFERSIZE] == 1
            assert handle.properties[cv2.CAP_PROP_CONVERT_RGB] == 1
        else:
            assert handle.properties[cv2.CAP_PROP_CONVERT_RGB] == 0


@pytest.mark.parametrize("failure", ["no_frame", "bad_shape", "wrong_dtype"])
def test_capture_failure_always_releases_camera_and_tracks_decode_errors(monkeypatch, failure):
    class Handle:
        released = False

        def read(self):
            if failure == "no_frame":
                return False, None
            return True, np.zeros(
                (8, 16, 3) if failure == "bad_shape" else (8, 16, 2),
                dtype=np.uint8 if failure == "bad_shape" else np.float32,
            )

        def release(self):
            self.released = True

    handle = Handle()
    monkeypatch.setattr(capture, "resolve_device", lambda _: "/dev/fake")
    monkeypatch.setattr(capture, "configure_controls", lambda *_: None)
    monkeypatch.setattr(capture, "open_capture", lambda *_: (handle, False))
    counters = CameraCounters()
    worker = capture.CaptureWorker(camera(), LatestFrameSlot(), counters, threading.Event())
    monkeypatch.setattr(worker.controls, "reapply", lambda _: None)
    with pytest.raises(capture.CameraError):
        worker._capture_until_failure()
    assert handle.released
    assert counters.captured == 0 and counters.decode_failures == int(failure != "no_frame")


def test_reconnect_backoff_is_bounded_and_stops_promptly(monkeypatch):
    class Stop:
        delays = []

        def is_set(self):
            return False

        def wait(self, delay):
            self.delays.append(delay)
            return len(self.delays) == 9

    stop = Stop()
    counters = CameraCounters()
    worker = capture.CaptureWorker(camera(), LatestFrameSlot(), counters, stop)

    def fail():
        raise capture.CameraError("USB unplugged")

    monkeypatch.setattr(worker, "_capture_until_failure", fail)
    worker.run()
    assert stop.delays == [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 5.0, 5.0, 5.0]
    assert counters.capture_failures == 9 and counters.reconnects == 8
    assert counters.state == CameraState.RETRY_WAIT


def test_disabled_capture_does_not_touch_device(monkeypatch):
    worker = capture.CaptureWorker(
        camera(enabled=False), LatestFrameSlot(), CameraCounters(), threading.Event()
    )
    monkeypatch.setattr(
        worker, "_capture_until_failure", lambda: pytest.fail("disabled device opened")
    )
    worker.run()
    assert worker.counters.state == CameraState.DISABLED
