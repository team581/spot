from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from spot_vision.capture import (
    CameraError,
    gray_to_yuyv_frame,
    orient_yuyv_frame,
    validate_yuyv_frame,
)
from spot_vision.config import CameraConfig, CameraSelector, DetectorConfig


def camera(format="YUY2"):
    return CameraConfig(
        id="front",
        enabled=True,
        selector=CameraSelector(device="/dev/video0"),
        format=format,
        width=1280,
        height=800,
        fps=60,
        calibration=None,
        timestamp_correction_us=0,
        detector=DetectorConfig(),
    )


def test_mjpeg_luma_packs_as_yuyv_with_neutral_chroma():
    configured = camera("MJPEG")
    gray = np.arange(configured.height * configured.width, dtype=np.uint8).reshape(
        configured.height, configured.width
    )
    packed = gray_to_yuyv_frame(gray, configured)
    assert validate_yuyv_frame(packed, configured) is packed
    assert np.array_equal(packed[..., 0], gray) and (packed[..., 1] == 128).all()
    with pytest.raises(CameraError):
        gray_to_yuyv_frame(gray[:, :-2], configured)


def test_frame_validation_rejects_shape_and_non_contiguous():
    config = replace(camera(), width=16, height=8)
    valid = np.zeros((8, 16, 2), dtype=np.uint8)
    assert validate_yuyv_frame(valid, config) is valid
    with pytest.raises(CameraError, match="shape"):
        validate_yuyv_frame(np.zeros((8, 16, 3), dtype=np.uint8), config)
    with pytest.raises(CameraError, match="strides"):
        validate_yuyv_frame(valid[:, ::-1], config)


def test_180_degree_orientation_preserves_packed_yuyv_chroma_and_stride():
    configured = replace(camera(), width=4, height=2, image_rotation_deg=180)
    raw = np.array(
        [
            [[10, 101], [20, 201], [30, 102], [40, 202]],
            [[50, 103], [60, 203], [70, 104], [80, 204]],
        ],
        dtype=np.uint8,
    )
    oriented = orient_yuyv_frame(raw, configured)
    assert oriented.tolist() == [
        [[80, 104], [70, 204], [60, 103], [50, 203]],
        [[40, 102], [30, 202], [20, 101], [10, 201]],
    ]
    assert validate_yuyv_frame(oriented, configured) is oriented
    assert np.array_equal(orient_yuyv_frame(oriented, configured), raw)
    assert orient_yuyv_frame(raw, replace(configured, image_rotation_deg=0)) is raw
