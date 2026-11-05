"""One bounded capture owner per physical device; hardware commands run here."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import cast

import numpy as np

from .capture import gray_to_yuyv_frame, orient_yuyv_frame
from .clock import FrameRateCounter, nt_now_us
from .config import CameraConfig, ConfigError
from .devices import _run, parse_capability_controls
from .models import CameraCounters, CameraState, FramePacket
from .queues import LatestFrameSlot
from .v4l2_capture import V4l2Capture


class VerifiedControls(dict):
    """Actual values plus refreshed UVC flags after automatic-control writes."""

    def __init__(self, values, capabilities):
        super().__init__(values)
        self.capabilities = list(capabilities.values())


def write_controls(device: str, requested: dict[str, float]) -> dict[str, float]:
    """Validate advertised units/menus, write and verify actual device readback."""
    deadline = time.monotonic() + 2.5

    def command(arguments):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ConfigError("Control transaction verification time exceeded")
        return _run(arguments, timeout=min(0.5, remaining))

    capabilities = {
        c["name"]: c
        for c in parse_capability_controls(
            command(["v4l2-ctl", "--device", device, "--list-ctrls-menus"])
        )
    }
    native = {}
    for name, value in requested.items():
        control = capabilities.get(name)
        if control is None:
            raise ConfigError(f"{name}: control unavailable")
        scaled = value / control["factor"]
        if (
            not np.isfinite(scaled)
            or scaled != int(scaled)
            or not control["min"] <= scaled <= control["max"]
            or (int(scaled) - control["min"]) % max(1, control["step"])
        ):
            raise ConfigError(f"{name}: value outside supported range or step")
        if control["options"] and scaled not in {o["value"] for o in control["options"]}:
            raise ConfigError(f"{name}: unsupported menu value")
        if (
            any(flag in control["flags"] for flag in ("read-only", "disabled", "grabbed"))
            and control["value"] != scaled
        ):
            raise ConfigError(f"{name}: device reports {control['flags']}")
        native[name] = int(scaled)
    # Mode controls precede dependent manual exposure controls. Re-enumerate
    # after each write because UVC auto settings change inactive flags.
    for name in sorted(native, key=lambda n: (0 if "auto" in n else 1, n)):
        if capabilities[name]["value"] != native[name]:
            fresh = {
                c["name"]: c
                for c in parse_capability_controls(
                    command(["v4l2-ctl", "--device", device, "--list-ctrls-menus"])
                )
            }
            if name not in fresh or not fresh[name]["writable"]:
                raise ConfigError(f"{name}: unavailable after applying automatic-control policy")
            command(["v4l2-ctl", "--device", device, f"--set-ctrl={name}={native[name]}"])
    actual = {
        c["name"]: c
        for c in parse_capability_controls(
            command(["v4l2-ctl", "--device", device, "--list-ctrls-menus"])
        )
    }
    readback = {
        name: actual[name]["value"] * actual[name]["factor"] for name in native if name in actual
    }
    if readback != requested:
        raise ConfigError(f"device clipped or rejected controls; readback {readback}")
    return VerifiedControls(readback, actual)


@dataclass
class ControlRequest:
    values: dict[str, float]
    done: threading.Event
    error: Exception | None = None
    result: dict[str, float] | None = None


class CameraCapture(threading.Thread):
    def __init__(
        self,
        camera: CameraConfig,
        device: str,
        generation: str,
        controls: dict[str, float],
        observer,
        *,
        capture_factory=V4l2Capture,
        control_writer=write_controls,
    ) -> None:
        super().__init__(name=f"uvc-{camera.id[:12]}", daemon=True)
        self.camera, self.device, self.generation = camera, device, generation
        self.requested = controls.copy()
        self.readback: dict[str, float] = {}
        self.capabilities = None
        self.observer = observer
        self.capture_factory, self.control_writer = capture_factory, control_writer
        self.stop_event, self.ready = threading.Event(), threading.Event()
        self.slot = LatestFrameSlot()
        self.counters = CameraCounters()
        self.commands: queue.Queue[ControlRequest] = queue.Queue(maxsize=1)
        self.last_progress = time.monotonic()
        self.verified = False
        self.timestamp_uncertainty_s = None
        self.timestamp_correction_us = 0
        self.frame = None
        self._lock = threading.RLock()

    def update(self, generation: str, values: dict) -> None:
        if not self.verified:
            raise ConfigError("camera unavailable; wait for verified recovery")
        request = ControlRequest(values.copy(), threading.Event())
        try:
            self.commands.put_nowait(request)
        except queue.Full as exc:
            raise ConfigError("camera control request already pending") from exc
        if not request.done.wait(3):
            raise RuntimeError("capture control worker stalled")
        if request.error:
            raise request.error
        with self._lock:
            self.requested, self.readback, self.generation = (
                values.copy(),
                cast(dict[str, float], request.result),
                generation,
            )
            self.capabilities = getattr(request.result, "capabilities", self.capabilities)
            self.slot.take()  # discard every pre-generation pending frame

    def stop(self) -> None:
        self.stop_event.set()
        self.slot.close()
        self.join(timeout=4)
        if self.is_alive():
            raise RuntimeError(f"capture worker did not stop: {self.name}")

    def run(self) -> None:
        import cv2

        delay = 0.1
        while not self.stop_event.is_set():
            self.last_progress = time.monotonic()
            capture = None
            self.verified = False
            try:
                self.counters.state = CameraState.CONFIGURING
                capture = self.capture_factory(cv2, self.camera, self.device)
                if capture.negotiated_fps is None:
                    raise ConfigError("Driver did not report a verified capture cadence")
                if abs(capture.negotiated_fps - self.camera.fps) > 0.1:
                    raise ConfigError(f"driver negotiated {capture.negotiated_fps:g} FPS")
                self.readback = self.control_writer(self.device, self.requested)
                self.capabilities = getattr(self.readback, "capabilities", None)
                capture_epoch = uuid.uuid4().hex
                sequence, previous_driver = 0, None
                rate = FrameRateCounter()
                while not self.stop_event.is_set():
                    self.last_progress = time.monotonic()
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        command = None
                    if command:
                        try:
                            command.result = self.control_writer(self.device, command.values)
                            capture_epoch = uuid.uuid4().hex
                        except Exception as exc:  # noqa: BLE001 - isolate backend/job failures at the worker boundary
                            command.error = exc
                        finally:
                            command.done.set()
                    with self._lock:
                        generation = self.generation
                        correction = self.timestamp_correction_us
                        uncertainty = self.timestamp_uncertainty_s
                    ok, image = capture.read()
                    captured_ns, local_us = time.monotonic_ns(), nt_now_us()
                    if not ok or image is None:
                        raise RuntimeError("bounded camera read returned no frame")
                    if self.camera.format in {"MJPG", "MJPEG"}:
                        image = gray_to_yuyv_frame(image, self.camera)
                    image = orient_yuyv_frame(image, self.camera)
                    # Explicitly own storage before returning it to consumers.
                    image = np.array(image, copy=True, order="C")
                    image.flags.writeable = False
                    sequence += 1
                    driver = capture.last_sequence
                    assert driver is not None
                    if previous_driver is not None:
                        self.counters.driver_sequence_gaps += max(0, (driver - previous_driver) - 1)
                    previous_driver = driver
                    packet = FramePacket(
                        self.camera.id,
                        sequence,
                        local_us + correction,
                        captured_ns + correction * 1000,
                        image,
                        capture_epoch,
                        generation,
                        timestamp_uncertainty_s=uncertainty,
                    )
                    self.frame = packet
                    if self.slot.put(packet):
                        self.counters.overwritten_before_processing += 1
                    self.counters.captured += 1
                    self.counters.fps_capture = rate.update(captured_ns / 1e9)
                    self.counters.state, self.counters.error = CameraState.RUNNING, ""
                    self.verified = True
                    self.ready.set()
                    self.observer(packet)
                    delay = 0.1
            except Exception as exc:  # noqa: BLE001 - isolate backend/job failures at the worker boundary
                self.counters.capture_failures += 1
                self.counters.error = str(exc)
                self.counters.state = CameraState.RETRY_WAIT
                self.ready.set()
            finally:
                self.verified = False
                if capture:
                    capture.release()
                while not self.commands.empty():
                    command = self.commands.get_nowait()
                    command.error = ConfigError("camera disconnected during control request")
                    command.done.set()
            # Wake periodically even during backoff so the watchdog distinguishes
            # an unavailable USB device from a blocked capture thread.
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline and not self.stop_event.wait(0.1):
                self.last_progress = time.monotonic()
            delay = min(5.0, delay * 2)
