from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from spot_vision import camera_capture
from spot_vision.camera_capture import CameraCapture, write_controls
from spot_vision.capture import gray_to_yuyv_frame, orient_yuyv_frame
from spot_vision.config import CameraConfig, CameraSelector, ConfigError, DetectorConfig


def capabilities(auto=3, exposure=25, gain=1):
    return f"""exposure_auto 0x009a0901 (menu) : min=0 max=3 default=3 value={auto}
        1: Manual Mode
        3: Aperture Priority Mode
exposure_time_absolute 0x009a0902 (int) : min=3 max=2047 step=1 default=25 value={exposure}{" flags=inactive" if auto == 3 else ""}
gain 0x00980913 (int) : min=0 max=100 step=1 default=1 value={gain}
"""


def test_auto_control_precedes_manual_write_and_returns_refreshed_flags(monkeypatch):
    actual = {"exposure_auto": 3, "exposure_time_absolute": 25, "gain": 1}
    writes = []

    def run(args, timeout):
        assert 0 < timeout <= 0.5
        if args[-1].startswith("--set-ctrl="):
            name, value = args[-1].split("=", 1)[1].split("=")
            actual[name] = int(value)
            writes.append(name)
            return ""
        return capabilities(
            actual["exposure_auto"], actual["exposure_time_absolute"], actual["gain"]
        )

    monkeypatch.setattr(camera_capture, "_run", run)
    result = write_controls("/dev/test", {"exposure_time_absolute": 3.0, "exposure_auto": 1})
    assert result == {"exposure_time_absolute": 3.0, "exposure_auto": 1}
    assert writes == ["exposure_auto", "exposure_time_absolute"]
    assert next(c for c in result.capabilities if c["name"] == "exposure_time_absolute")["writable"]


def test_clipped_control_readback_cannot_acknowledge_success(monkeypatch):
    monkeypatch.setattr(
        camera_capture,
        "_run",
        lambda args, timeout: "" if args[-1].startswith("--set-ctrl=") else capabilities(),
    )
    with pytest.raises(ConfigError, match="clipped or rejected"):
        write_controls("/dev/test", {"gain": 30})


def test_out_of_range_control_error_names_value_and_range_in_api_units(monkeypatch):
    monkeypatch.setattr(camera_capture, "_run", lambda args, timeout: capabilities())
    with pytest.raises(
        ConfigError, match=r"exposure_time_absolute: 5000 ms is outside 0.3–204.7 ms"
    ):
        write_controls("/dev/test", {"exposure_time_absolute": 5000})


def test_rejected_controls_mark_attached_camera_as_recoverable():
    def reject(device, values, *, reset_defaults=False):
        raise ConfigError("gain: rejected")

    worker = CameraCapture(
        CameraConfig(
            "test",
            True,
            CameraSelector(device="/dev/test"),
            "YUYV",
            8,
            8,
            30,
            None,
            0,
            DetectorConfig(),
        ),
        "/dev/test",
        "old",
        {"gain": 1},
        lambda packet: None,
        capture_factory=lambda *args: type(
            "Capture", (), {"negotiated_fps": 30, "release": lambda self: None}
        )(),
        control_writer=reject,
    )
    worker.start()
    try:
        assert worker.ready.wait(1)
        assert worker.controls_rejected and not worker.verified
    finally:
        worker.stop()


def test_unknown_control_never_writes_device(monkeypatch):
    calls = []
    monkeypatch.setattr(
        camera_capture, "_run", lambda args, timeout: calls.append(args) or capabilities()
    )
    with pytest.raises(ConfigError, match="unavailable"):
        write_controls("/dev/test", {"invented": 1})
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("initial_auto", "requested", "expected"),
    [
        (1, {}, {"exposure_auto": 3, "gain": 1}),
        (3, {"exposure_auto": 1}, {"exposure_auto": 1, "exposure_time_absolute": 2.5, "gain": 1}),
    ],
)
def test_defaults_follow_effective_automatic_policy(monkeypatch, initial_auto, requested, expected):
    actual = {"exposure_auto": initial_auto, "exposure_time_absolute": 60, "gain": 8}
    writes = []

    def run(args, timeout):
        if args[-1].startswith("--set-ctrl="):
            name, value = args[-1].split("=", 1)[1].split("=")
            if name == "exposure_time_absolute":
                assert actual["exposure_auto"] == 1
            actual[name] = int(value)
            writes.append(name)
            return ""
        return capabilities(
            actual["exposure_auto"], actual["exposure_time_absolute"], actual["gain"]
        )

    monkeypatch.setattr(camera_capture, "_run", run)
    result = write_controls("/dev/test", requested, reset_defaults=True)
    assert result == expected
    assert writes[0] == "exposure_auto"
    assert ("exposure_time_absolute" in writes) == (actual["exposure_auto"] == 1)


def test_explicit_manual_control_cannot_be_ignored_in_automatic_mode(monkeypatch):
    monkeypatch.setattr(camera_capture, "_run", lambda args, timeout: capabilities())
    with pytest.raises(ConfigError, match="unavailable after applying automatic-control policy"):
        write_controls("/dev/test", {"exposure_time_absolute": 3}, reset_defaults=True)


def test_preview_does_not_reset_hardware_controls(monkeypatch):
    def run(args, timeout):
        assert not args[-1].startswith("--set-ctrl=")
        return capabilities(auto=1, exposure=60, gain=8)

    monkeypatch.setattr(camera_capture, "_run", run)
    assert write_controls("/dev/test", {}) == {}


def test_owner_controls_and_frames_are_serialized_with_owned_readonly_storage():
    original = np.zeros((8, 8, 2), np.uint8)
    owners = []
    frames = []

    class Capture:
        negotiated_fps = 30
        last_sequence = 1

        def __init__(self, *args):
            pass

        def read(self):
            time.sleep(0.002)
            return True, original

        def release(self):
            pass

    def controls(device, values, *, reset_defaults=False):
        owners.append(threading.current_thread().name)
        return values.copy()

    worker = CameraCapture(
        CameraConfig(
            "test",
            True,
            CameraSelector(device="/dev/test"),
            "YUYV",
            8,
            8,
            30,
            None,
            0,
            DetectorConfig(),
        ),
        "/dev/test",
        "old",
        {"gain": 1},
        frames.append,
        capture_factory=Capture,
        control_writer=controls,
    )
    worker.start()
    try:
        assert worker.ready.wait(1) and worker.verified
        worker.update("new", {"gain": 2})
        deadline = time.monotonic() + 1
        while (
            not frames or frames[-1].runtime_generation != "new"
        ) and time.monotonic() < deadline:
            time.sleep(0.002)
        packet = frames[-1]
        assert packet.runtime_generation == "new"
        assert not packet.image.flags.writeable and not np.shares_memory(packet.image, original)
        original[:] = 255
        assert packet.image.max() == 0
        assert len(owners) == 2 and set(owners) == {worker.name}
        assert frames[0].capture_epoch != packet.capture_epoch
    finally:
        worker.stop()


@pytest.mark.parametrize("pixel_format", ["YUYV", "MJPG"])
def test_capture_reconnect_releases_buffers_and_resets_epoch_and_sequence(pixel_format):
    camera = CameraConfig(
        "test",
        True,
        CameraSelector(),
        pixel_format,
        8,
        8,
        30,
        None,
        0,
        DetectorConfig(),
        image_rotation_deg=180,
    )
    raw = np.arange(128, dtype=np.uint8).reshape(8, 8, 2)
    gray = np.full((8, 8), 64, np.uint8)
    captures, frames = [], []

    class Capture:
        negotiated_fps = 30

        def __init__(self, *_):
            self.last_sequence = 40
            self.released = False
            captures.append(self)

        def read(self):
            self.last_sequence += 1
            if self.last_sequence == 43:
                return False, None
            return True, gray if pixel_format == "MJPG" else raw

        def release(self):
            self.released = True

    def observe(packet):
        frames.append(packet)
        if len(frames) == 3:
            worker.stop_event.set()

    worker = CameraCapture(
        camera,
        "/dev/test",
        "generation",
        {},
        observe,
        capture_factory=Capture,
        control_writer=lambda _, values, **kwargs: values,
    )
    worker.start()
    try:
        worker.join(timeout=2)
        assert not worker.is_alive()
        expected = gray_to_yuyv_frame(gray, camera) if pixel_format == "MJPG" else raw
        assert np.array_equal(frames[0].image, orient_yuyv_frame(expected, camera))
        assert [frame.sequence for frame in frames] == [1, 2, 1]
        assert frames[0].capture_epoch == frames[1].capture_epoch != frames[2].capture_epoch
        assert worker.counters.capture_failures == 1
        assert len(captures) == 2 and all(capture.released for capture in captures)
    finally:
        worker.stop()
