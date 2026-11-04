"""Persistent device selection and camera enumeration regressions."""

from types import SimpleNamespace

import pytest

from spot_vision import capture
from spot_vision.config import CameraSelector


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
        lambda args, **_kw: SimpleNamespace(
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
