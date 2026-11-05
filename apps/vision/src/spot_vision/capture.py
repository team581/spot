from __future__ import annotations

import numpy as np

from .config import CameraConfig


class CameraError(RuntimeError):
    pass


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


def gray_to_yuyv_frame(frame: np.ndarray, camera: CameraConfig) -> np.ndarray:
    """Pack decoded luma as YUYV with neutral chroma; detection only reads luma."""
    expected = (camera.height, camera.width)
    if frame.dtype != np.uint8 or frame.shape != expected:
        raise CameraError(f"expected grayscale shape {expected}, received {frame.shape}")
    packed = np.full((*expected, 2), 128, np.uint8)
    packed[..., 0] = frame
    return packed
