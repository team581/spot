"""Advertised optical-mode eligibility for capture and preview."""

from __future__ import annotations

from . import protocol_models as wire


def mode_supported(device, mode) -> bool:
    fmt = (
        "YUYV"
        if mode.pixel_format in {"YUY2", "YUYV"}
        else "MJPG"
        if mode.pixel_format in {"MJPG", "MJPEG"}
        else mode.pixel_format
    )
    return any(
        m["width"] == mode.width
        and m["height"] == mode.height
        and m["pixel_format"] == fmt
        and abs(m["fps"] - mode.fps) < 0.1
        for m in device.modes
    )


def preview_modes(device):
    return [
        mode
        for mode in device.modes
        if mode["pixel_format"] in {"MJPG", "YUYV"}
        and 16 <= mode["width"] <= 1920
        and 16 <= mode["height"] <= 1080
        and mode["width"] % 8 == 0
        and mode["height"] % 8 == 0
        and 0 < mode["fps"] <= 240
        and mode["width"] * mode["height"] * mode["fps"] <= 640 * 480 * 240
    ]


def preview_mode(mode):
    return wire.OpticalMode(
        id="preview",
        fps=round(mode["fps"]),
        **{key: mode[key] for key in ("width", "height", "pixel_format")},
    )
