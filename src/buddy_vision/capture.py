from __future__ import annotations

import glob
import logging
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from .clock import nt_now_us
from .config import CameraConfig, CameraSelector
from .models import CameraCounters, CameraState, FramePacket
from .queues import LatestFrameSlot

LOGGER = logging.getLogger(__name__)


class CameraError(RuntimeError):
    pass


def _real_device(path: str) -> str:
    resolved = str(Path(path).resolve())
    if not Path(resolved).exists():
        raise CameraError(f"camera device does not exist: {path}")
    return resolved


def resolve_device(selector: CameraSelector) -> str:
    if selector.device:
        return _real_device(selector.device)
    if selector.by_id:
        candidate = selector.by_id
        if not candidate.startswith("/"):
            candidate = f"/dev/v4l/by-id/{candidate}"
        return _real_device(candidate)
    if selector.by_path:
        candidate = selector.by_path
        if not candidate.startswith("/"):
            candidate = f"/dev/v4l/by-path/{candidate}"
        return _real_device(candidate)
    if selector.serial:
        for candidate in sorted(glob.glob("/dev/v4l/by-id/*")):
            if selector.serial in Path(candidate).name:
                return _real_device(candidate)
        for candidate in sorted(glob.glob("/dev/video*")):
            result = subprocess.run(
                ["udevadm", "info", "--query=property", f"--name={candidate}"],
                check=False, capture_output=True, text=True,
            )
            properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            if properties.get("ID_SERIAL_SHORT") == selector.serial:
                return _real_device(candidate)
        raise CameraError(f"no camera with serial {selector.serial!r}")
    raise CameraError("camera selector is empty")


def enumerate_camera(device: str) -> str:
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device", device, "--all", "--list-formats-ext", "--list-ctrls-menus"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError as exc:
        raise CameraError("v4l2-ctl is required to enumerate cameras") from exc
    if result.returncode:
        raise CameraError(result.stderr.strip() or f"v4l2-ctl failed with {result.returncode}")
    return result.stdout


def build_gstreamer_pipeline(camera: CameraConfig, device: str) -> str:
    source = f'v4l2src device="{device}" io-mode=2'
    dimensions = f"width={camera.width},height={camera.height},framerate={camera.fps}/1"
    if camera.format in {"MJPG", "MJPEG"}:
        stages = [source, f"image/jpeg,{dimensions}", "jpegdec", "videoconvert",
                  "video/x-raw,format=YUY2"]
    elif camera.format in {"YUY2", "YUYV"}:
        stages = [source, f"video/x-raw,format=YUY2,{dimensions}"]
    else:
        raise CameraError(f"unsupported first-pass camera format {camera.format!r}")
    stages.append("appsink drop=true max-buffers=1 sync=false")
    return " ! ".join(stages)


def _set_control(device: str, name: str, value: int) -> bool:
    result = subprocess.run(
        ["v4l2-ctl", "--device", device, f"--set-ctrl={name}={value}"],
        check=False, capture_output=True, text=True,
    )
    return result.returncode == 0


def configure_controls(camera: CameraConfig, device: str) -> None:
    if camera.auto_exposure:
        _set_control(device, "exposure_auto", 3) or _set_control(device, "auto_exposure", 3)
    else:
        _set_control(device, "exposure_auto", 1) or _set_control(device, "auto_exposure", 1)
        # UVC exposure_absolute is conventionally measured in 100 us units.
        if (camera.exposure_us is not None
                and not _set_control(device, "exposure_time_absolute", camera.exposure_us)
                and not _set_control(device, "exposure_absolute", max(1, camera.exposure_us // 100))):
            raise CameraError("camera does not expose a supported manual exposure control")
    if camera.gain is not None and not _set_control(device, "gain", camera.gain):
        raise CameraError("camera does not expose a gain control")


def validate_yuyv_frame(frame: np.ndarray, camera: CameraConfig) -> np.ndarray:
    if frame.dtype != np.uint8:
        raise CameraError(f"expected uint8 frame, received {frame.dtype}")
    expected = (camera.height, camera.width, 2)
    if frame.shape != expected:
        raise CameraError(f"expected YUYV shape {expected}, received {frame.shape}")
    if not frame.flags.c_contiguous or frame.strides != (camera.width * 2, 2, 1):
        raise CameraError(f"expected packed YUYV strides, received {frame.strides}")
    return frame


class CaptureWorker(threading.Thread):
    def __init__(self, camera: CameraConfig, slot: LatestFrameSlot, counters: CameraCounters,
                 stop_event: threading.Event) -> None:
        super().__init__(name=f"capture-{camera.id}", daemon=True)
        self.camera = camera
        self.slot = slot
        self.counters = counters
        self.stop_event = stop_event

    def run(self) -> None:
        if not self.camera.enabled:
            self.counters.state = CameraState.DISABLED
            return
        delay = 0.1
        while not self.stop_event.is_set():
            try:
                self._capture_until_failure()
                delay = 0.1
            except Exception as exc:  # noqa: BLE001 - camera backends raise several exception types
                self.counters.capture_failures += 1
                self.counters.error = str(exc)
                self.counters.state = CameraState.RETRY_WAIT
                LOGGER.warning("camera %s failed: %s", self.camera.id, exc)
                if self.stop_event.wait(delay):
                    return
                delay = min(delay * 2.0, 5.0)
                self.counters.reconnects += 1

    def _capture_until_failure(self) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise CameraError("OpenCV is required for camera capture") from exc
        self.counters.state = CameraState.DISCOVERING
        device = resolve_device(self.camera.selector)
        self.counters.state = CameraState.CONFIGURING
        configure_controls(self.camera, device)
        pipeline = build_gstreamer_pipeline(self.camera, device)
        capture = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        capture.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        if not capture.isOpened():
            raise CameraError(f"could not open pipeline: {pipeline}")
        sequence = 0
        previous_capture = time.monotonic()
        successful_since = previous_capture
        try:
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                monotonic_ns = time.monotonic_ns()
                if not ok or frame is None:
                    raise CameraError("capture returned no frame")
                try:
                    image = validate_yuyv_frame(frame, self.camera)
                except CameraError:
                    self.counters.decode_failures += 1
                    raise
                sequence += 1
                now = monotonic_ns / 1e9
                interval = now - previous_capture
                previous_capture = now
                if interval > 0:
                    instantaneous = 1.0 / interval
                    self.counters.fps_capture = (instantaneous if self.counters.fps_capture == 0
                                                 else 0.9 * self.counters.fps_capture + 0.1 * instantaneous)
                packet = FramePacket(
                    camera_id=self.camera.id,
                    sequence=sequence,
                    camera_frame_sequence=sequence,
                    capture_timestamp_us=nt_now_us() + self.camera.timestamp_correction_us,
                    captured_monotonic_ns=monotonic_ns,
                    image=image,
                )
                if self.slot.put(packet):
                    self.counters.overwritten_before_processing += 1
                self.counters.captured += 1
                self.counters.last_capture_monotonic = now
                self.counters.state = (CameraState.CONFIG_MISMATCH
                                       if self.counters.configuration_error else CameraState.RUNNING)
                self.counters.error = self.counters.configuration_error
                if now - successful_since >= 10.0:
                    successful_since = now
        finally:
            capture.release()
