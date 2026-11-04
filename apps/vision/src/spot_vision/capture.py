from __future__ import annotations

import glob
import subprocess
from pathlib import Path

import numpy as np

from .config import CameraConfig, CameraSelector


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
