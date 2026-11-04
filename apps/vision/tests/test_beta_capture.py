from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from spot_vision import beta_capture
from spot_vision.beta_capture import BetaCapture, write_controls
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

    monkeypatch.setattr(beta_capture, "_run", run)
    result = write_controls("/dev/test", {"exposure_time_absolute": 3000.0, "exposure_auto": 1})
    assert result == {"exposure_time_absolute": 3000.0, "exposure_auto": 1}
    assert writes == ["exposure_auto", "exposure_time_absolute"]
    assert next(c for c in result.capabilities if c["name"] == "exposure_time_absolute")["writable"]


def test_clipped_control_readback_cannot_acknowledge_success(monkeypatch):
    monkeypatch.setattr(
        beta_capture,
        "_run",
        lambda args, timeout: "" if args[-1].startswith("--set-ctrl=") else capabilities(),
    )
    with pytest.raises(ConfigError, match="clipped or rejected"):
        write_controls("/dev/test", {"gain": 30})


def test_unknown_control_never_writes_device(monkeypatch):
    calls = []
    monkeypatch.setattr(
        beta_capture, "_run", lambda args, timeout: calls.append(args) or capabilities()
    )
    with pytest.raises(ConfigError, match="unavailable"):
        write_controls("/dev/test", {"invented": 1})
    assert len(calls) == 1


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

    def controls(device, values):
        owners.append(threading.current_thread().name)
        return values.copy()

    worker = BetaCapture(
        CameraConfig(
            "test",
            True,
            CameraSelector(device="/dev/test"),
            "YUYV",
            8,
            8,
            30,
            None,
            None,
            False,
            None,
            0,
            1,
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
