from __future__ import annotations

import glob
import logging
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from .camera_controls import CameraControls
from .clock import FrameRateCounter, nt_now_us
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
                check=False,
                capture_output=True,
                text=True,
            )
            properties = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            if properties.get("ID_SERIAL_SHORT") == selector.serial:
                return _real_device(candidate)
        raise CameraError(f"no camera with serial {selector.serial!r}")
    raise CameraError("camera selector is empty")


def enumerate_camera(device: str) -> str:
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device", device, "--all", "--list-formats-ext", "--list-ctrls-menus"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
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
        stages = [
            source,
            f"image/jpeg,{dimensions}",
            "jpegdec",
            "videoconvert",
            "video/x-raw,format=YUY2",
        ]
    elif camera.format in {"YUY2", "YUYV"}:
        stages = [source, f"video/x-raw,format=YUY2,{dimensions}"]
    else:
        raise CameraError(f"unsupported first-pass camera format {camera.format!r}")
    stages.append("appsink drop=true max-buffers=1 sync=false")
    return " ! ".join(stages)


def _set_control(device: str, name: str, value: int) -> bool:
    result = subprocess.run(
        ["v4l2-ctl", "--device", device, f"--set-ctrl={name}={value}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def configure_controls(camera: CameraConfig, device: str) -> None:
    if camera.auto_exposure:
        _set_control(device, "exposure_auto", 3) or _set_control(device, "auto_exposure", 3)
    else:
        _set_control(device, "exposure_auto", 1) or _set_control(device, "auto_exposure", 1)
        # Both V4L2 UVC spellings use 100 us units, while the public config is
        # intentionally expressed in microseconds.
        exposure_units = None if camera.exposure_us is None else max(1, camera.exposure_us // 100)
        if (
            camera.exposure_us is not None
            and not _set_control(device, "exposure_time_absolute", exposure_units)
            and not _set_control(device, "exposure_absolute", exposure_units)
        ):
            raise CameraError("camera does not expose a supported manual exposure control")
    if camera.gain is not None and not _set_control(device, "gain", camera.gain):
        raise CameraError("camera does not expose a gain control")
    for name in ("contrast", "sharpness"):
        value = getattr(camera, name, None)
        if value is not None and not _set_control(device, name, value):
            raise CameraError(f"camera does not expose a supported {name} control")


def validate_yuyv_frame(frame: np.ndarray, camera: CameraConfig) -> np.ndarray:
    if frame.dtype != np.uint8:
        raise CameraError(f"expected uint8 frame, received {frame.dtype}")
    expected = (camera.height, camera.width, 2)
    if frame.shape != expected:
        raise CameraError(f"expected YUYV shape {expected}, received {frame.shape}")
    if not frame.flags.c_contiguous or frame.strides != (camera.width * 2, 2, 1):
        raise CameraError(f"expected packed YUYV strides, received {frame.strides}")
    return frame


def orient_yuyv_frame(frame: np.ndarray, camera: CameraConfig) -> np.ndarray:
    """Apply the configured optical-axis rotation without breaking YUYV pairs."""
    frame = validate_yuyv_frame(frame, camera)
    if camera.image_rotation_deg == 0:
        return frame
    if camera.image_rotation_deg != 180 or camera.width % 2:
        raise CameraError("unsupported packed YUYV image rotation")
    # YUYV stores two pixels as Y0 U Y1 V. Reverse the pairs and rows, then
    # exchange only Y0 and Y1 within each pair; U and V stay in their slots.
    pairs = frame.reshape(camera.height, camera.width // 2, 4)
    rotated = np.ascontiguousarray(pairs[::-1, ::-1])
    rotated[..., 0], rotated[..., 2] = pairs[::-1, ::-1, 2], pairs[::-1, ::-1, 0]
    return rotated.reshape(camera.height, camera.width, 2)


def bgr_to_yuyv_frame(frame: np.ndarray, camera: CameraConfig, cv2) -> np.ndarray:
    expected = (camera.height, camera.width, 3)
    if frame.dtype != np.uint8 or frame.shape != expected:
        raise CameraError(f"expected BGR shape {expected}, received {frame.shape}")
    conversion = getattr(cv2, "COLOR_BGR2YUV_YUY2", None)
    if conversion is None:
        raise CameraError("OpenCV does not provide BGR-to-YUYV conversion")
    return validate_yuyv_frame(cv2.cvtColor(frame, conversion), camera)


def open_capture(cv2, camera: CameraConfig, device: str):
    """Use bounded MJPEG reads on Linux; otherwise prefer GStreamer."""
    if sys.platform.startswith("linux") and camera.format in {"MJPG", "MJPEG"}:
        from .v4l2_capture import MjpegCapture

        return MjpegCapture(cv2, camera, device), True
    pipeline = build_gstreamer_pipeline(camera, device)
    capture = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    capture.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    if capture.isOpened():
        return capture, False

    capture.release()
    LOGGER.warning(
        "camera %s could not open GStreamer pipeline; falling back to direct V4L2",
        camera.id,
    )
    capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    fourcc_name = "MJPG" if camera.format in {"MJPG", "MJPEG"} else "YUYV"
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc_name))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, camera.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, camera.height)
    capture.set(cv2.CAP_PROP_FPS, camera.fps)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    capture.set(cv2.CAP_PROP_CONVERT_RGB, 1)
    if not capture.isOpened():
        capture.release()
        raise CameraError(f"could not open pipeline or direct V4L2 device: {pipeline}")
    return capture, True


class CaptureWorker(threading.Thread):
    def __init__(
        self,
        camera: CameraConfig,
        slot: LatestFrameSlot,
        counters: CameraCounters,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name=f"capture-{camera.id}", daemon=True)
        self.camera = camera
        self.slot = slot
        self.counters = counters
        self.stop_event = stop_event
        self.controls = CameraControls(camera)

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
        with self.controls.lock:
            configure_controls(self.camera, device)
            self.controls.reapply(device)
        capture, converts_from_bgr = open_capture(cv2, self.camera, device)
        capture_epoch = uuid.uuid4().hex
        sequence = 0
        frame_rate = FrameRateCounter()
        self.counters.fps_capture = 0.0
        successful_since = time.monotonic()
        try:
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                monotonic_ns = time.monotonic_ns()
                if not ok or frame is None:
                    raise CameraError("capture returned no frame")
                try:
                    decoded = (
                        bgr_to_yuyv_frame(frame, self.camera, cv2)
                        if converts_from_bgr
                        else validate_yuyv_frame(frame, self.camera)
                    )
                    image = orient_yuyv_frame(decoded, self.camera)
                except CameraError:
                    self.counters.decode_failures += 1
                    raise
                sequence += 1
                now = monotonic_ns / 1e9
                self.counters.fps_capture = frame_rate.update(now)
                packet = FramePacket(
                    camera_id=self.camera.id,
                    sequence=sequence,
                    camera_frame_sequence=sequence,
                    capture_timestamp_us=nt_now_us() + self.camera.timestamp_correction_us,
                    captured_monotonic_ns=monotonic_ns,
                    image=image,
                    capture_epoch=capture_epoch,
                )
                if self.slot.put(packet):
                    self.counters.overwritten_before_processing += 1
                self.counters.captured += 1
                self.counters.last_capture_monotonic = now
                self.counters.state = (
                    CameraState.CONFIG_MISMATCH
                    if self.counters.configuration_error
                    else CameraState.RUNNING
                )
                self.counters.error = self.counters.configuration_error
                if now - successful_since >= 10.0:
                    successful_since = now
        finally:
            capture.release()
