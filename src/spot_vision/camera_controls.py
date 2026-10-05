"""Discover and tune UVC image controls without opening a second capture stream."""
from __future__ import annotations

import re
import subprocess
import threading


# Only image controls: trigger, flips and capture modes can invalidate the pipeline.
CONTROL_INFO = {
    "auto_exposure": ("Exposure mode", "Choose Manual Mode to set a fixed exposure."),
    "exposure_auto": ("Exposure mode", "Choose Manual Mode to set a fixed exposure."),
    "exposure_time_absolute": ("Exposure", "Shorter exposure reduces motion blur; longer exposure collects more light."),
    "exposure_absolute": ("Exposure", "Shorter exposure reduces motion blur; longer exposure collects more light."),
    "gain": ("Gain", "Amplifies the image; higher values can increase noise."),
    "brightness": ("Black level / brightness", "Offsets image luminance, including the darkest pixels."),
    "black_level": ("Black level", "Adjusts the darkest image level."),
    "contrast": ("Contrast", "Adjusts luminance gain and the separation of dark and bright pixels."),
    "gamma": ("Gamma", "Adjusts the tonal response of midtones. Units depend on firmware."),
    "sharpness": ("Sharpness", "Adjusts edge enhancement; too much can introduce halos around tags."),
    "backlight_compensation": ("Backlight compensation", "Compensates for bright backgrounds."),
    "power_line_frequency": ("Anti-flicker", "Select the local lighting frequency."),
    "white_balance_automatic": ("Auto white balance", "Automatically adjusts color balance."),
    "white_balance_temperature_auto": ("Auto white balance", "Automatically adjusts color balance."),
    "white_balance_temperature": ("White balance", "Color temperature in kelvin; disable auto white balance to adjust."),
    "saturation": ("Saturation", "Adjusts color intensity; may have no effect on monochrome cameras."),
    "hue": ("Hue", "Adjusts color balance; may have no effect on monochrome cameras."),
    "autogain": ("Auto gain", "Automatically adjusts image gain."),
}
EXPOSURE_NAMES = {"exposure_time_absolute", "exposure_absolute"}
HEADER = re.compile(r"^\s*(\w+)\s+0x[0-9a-fA-F]+\s+\(([^)]+)\)\s*:\s*(.*)$")


class ControlError(RuntimeError):
    pass


def parse_controls(output: str) -> list[dict]:
    controls, current = [], None
    for line in output.splitlines():
        match = HEADER.match(line)
        if match:
            name, kind, attributes = match.groups()
            current = None
            if name not in CONTROL_INFO or kind not in {"int", "bool", "menu", "intmenu"}:
                continue
            numbers = {key: int(value) for key, value in
                       re.findall(r"(min|max|step|default|value)=(-?\d+)", attributes)}
            if "value" not in numbers:
                continue
            flags = attributes.split("flags=", 1)[1].strip() if "flags=" in attributes else ""
            label, description = CONTROL_INFO[name]
            factor = 100 if name in EXPOSURE_NAMES else 1
            current = dict(name=name, type=kind, label=label, description=description,
                           min=numbers.get("min", 0), max=numbers.get("max", 1),
                           step=numbers.get("step", 1), default=numbers.get("default"),
                           value=numbers["value"], flags=flags, options=[], factor=factor,
                           unit="µs" if factor == 100 else "K" if name == "white_balance_temperature" else "",
                           writable=not any(flag in flags for flag in
                                            ("inactive", "read-only", "disabled", "grabbed")))
            controls.append(current)
        elif current and current["type"] in {"menu", "intmenu"}:
            option = re.match(r"^\s+(-?\d+):\s*(.+)$", line)
            if option:
                current["options"].append({"value": int(option[1]), "label": option[2]})
    values = {item["name"]: item["value"] for item in controls}
    for item in controls:
        automatic = (item["name"] in EXPOSURE_NAMES and
                     values.get("auto_exposure", values.get("exposure_auto", 1)) != 1)
        automatic |= (item["name"] == "white_balance_temperature" and
                      bool(values.get("white_balance_automatic",
                                      values.get("white_balance_temperature_auto", 0))))
        automatic |= item["name"] == "gain" and bool(values.get("autogain", 0))
        if automatic:
            item["writable"] = False
            item["flags"] = (item["flags"] + ", automatic mode").strip(", ")
    # Stable order puts the essential tuning controls first.
    return sorted(controls, key=lambda item: (item["name"] not in {
        "auto_exposure", "exposure_auto", "autogain", "white_balance_automatic",
        "white_balance_temperature_auto"}, list(CONTROL_INFO).index(item["name"])))


def _run(device: str, argument: str) -> str:
    try:
        result = subprocess.run(["v4l2-ctl", "--device", device, argument],
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ControlError(f"Camera controls unavailable: {exc}") from exc
    if result.returncode:
        raise ControlError(result.stderr.strip() or "Camera control command failed")
    return result.stdout


class CameraControls:
    def __init__(self, camera) -> None:
        self.camera = camera
        self.lock = threading.RLock()
        self.overrides: dict[str, int] = {}

    def _device(self) -> str:
        from .capture import resolve_device
        return resolve_device(self.camera.selector)

    def read(self) -> list[dict]:
        with self.lock:
            return parse_controls(_run(self._device(), "--list-ctrls-menus"))

    def set(self, name: str, value: int) -> list[dict]:
        with self.lock:
            device = self._device()
            controls = parse_controls(_run(device, "--list-ctrls-menus"))
            control = next((item for item in controls if item["name"] == name), None)
            if control is None:
                raise ValueError("This camera does not support that image control")
            if not control["writable"]:
                raise ValueError("Control is inactive or read-only; disable its automatic mode first")
            if type(value) is not int:
                raise ValueError("Control value must be an integer")
            if (not control["min"] <= value <= control["max"] or
                    (value - control["min"]) % control["step"]):
                raise ValueError("Control value is outside the supported range or step")
            if control["type"] in {"menu", "intmenu"} and value not in {
                    option["value"] for option in control["options"]}:
                raise ValueError("Unsupported menu option")
            _run(device, f"--set-ctrl={name}={value}")
            controls = parse_controls(_run(device, "--list-ctrls-menus"))
            actual = next((item for item in controls if item["name"] == name), None)
            if actual is None or actual["value"] != value:
                raise ControlError("Camera did not retain the requested value; refresh controls")
            self.overrides[name] = actual["value"]
            return controls

    def reapply(self, device: str) -> None:
        """Called under lock after startup defaults, including after USB reconnects."""
        controls = parse_controls(_run(device, "--list-ctrls-menus")) if self.overrides else []
        for control in controls:
            name = control["name"]
            if name in self.overrides:
                current = next((item for item in parse_controls(
                    _run(device, "--list-ctrls-menus")) if item["name"] == name), None)
                if current and current["writable"]:
                    _run(device, f"--set-ctrl={name}={self.overrides[name]}")
