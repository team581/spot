"""Discover and tune UVC image controls without opening a second capture stream."""

from __future__ import annotations

import math
import re

# Only image controls: trigger, flips and capture modes can invalidate the pipeline.
CONTROL_INFO = {
    "auto_exposure": ("Exposure mode", "Choose Manual Mode to set a fixed exposure."),
    "exposure_auto": ("Exposure mode", "Choose Manual Mode to set a fixed exposure."),
    "exposure_time_absolute": (
        "Exposure",
        "Shorter exposure reduces motion blur; longer exposure collects more light.",
    ),
    "exposure_absolute": (
        "Exposure",
        "Shorter exposure reduces motion blur; longer exposure collects more light.",
    ),
    "gain": ("Gain", "Amplifies the image; higher values can increase noise."),
    "brightness": (
        "Black level / brightness",
        "Offsets image luminance, including the darkest pixels.",
    ),
    "black_level": ("Black level", "Adjusts the darkest image level."),
    "contrast": (
        "Contrast",
        "Adjusts luminance gain and the separation of dark and bright pixels.",
    ),
    "gamma": ("Gamma", "Adjusts the tonal response of midtones. Units depend on firmware."),
    "sharpness": (
        "Sharpness",
        "Adjusts edge enhancement; too much can introduce halos around tags.",
    ),
    "backlight_compensation": ("Backlight compensation", "Compensates for bright backgrounds."),
    "power_line_frequency": ("Anti-flicker", "Select the local lighting frequency."),
    "white_balance_automatic": ("Auto white balance", "Automatically adjusts color balance."),
    "white_balance_temperature_auto": (
        "Auto white balance",
        "Automatically adjusts color balance.",
    ),
    "white_balance_temperature": (
        "White balance",
        "Color temperature in kelvin; disable auto white balance to adjust.",
    ),
    "saturation": (
        "Saturation",
        "Adjusts color intensity; may have no effect on monochrome cameras.",
    ),
    "hue": ("Hue", "Adjusts color balance; may have no effect on monochrome cameras."),
    "autogain": ("Auto gain", "Automatically adjusts image gain."),
}
EXPOSURE_NAMES = {"exposure_time_absolute", "exposure_absolute"}
HEADER = re.compile(r"^\s*(\w+)\s+0x[0-9a-fA-F]+\s+\(([^)]+)\)\s*:\s*(.*)$")


def scaled(value: float, factor: float) -> float:
    """Convert a driver value to UI/API units without float noise (e.g. 100 µs steps to ms)."""
    return round(value * factor, 6)


def frame_limited_exposure(control: dict, fps: float) -> dict:
    """Bound a millisecond UI/API range to one configured capture interval."""
    if control["name"] not in EXPOSURE_NAMES or not fps or fps <= 0:
        return control
    result = dict(control)
    minimum, step = control["min"], control["step"] or 1
    maximum = min(control["max"], 1000 / fps)
    limited = scaled(minimum + math.floor(round((maximum - minimum) / step, 6)) * step, 1)
    result["hardware_max"] = control["max"]
    result["max"] = max(minimum, limited)
    result["exposure_limit_available"] = limited >= minimum
    result["range_reason"] = f"{fps:g} FPS exposure limit"
    if limited < minimum:
        result["allowed"] = False
        result["reason"] = (
            "Minimum exposure exceeds the frame interval; choose a lower capture rate"
        )
    return result
