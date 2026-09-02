from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from buddy_vision.capture import CameraError, build_gstreamer_pipeline, validate_yuyv_frame
from buddy_vision.config import CameraConfig, CameraSelector, DetectorConfig


def camera(format="YUY2"):
    return CameraConfig(
        id="front", enabled=True, selector=CameraSelector(device="/dev/video0"),
        format=format, width=1280, height=800, fps=60, exposure_us=1000, gain=20,
        auto_exposure=False, calibration=None, timestamp_correction_us=0,
        config_revision=1, detector=DetectorConfig(),
    )


def test_raw_pipeline_requests_packed_yuy2():
    pipeline = build_gstreamer_pipeline(camera(), "/dev/video4")
    assert 'device="/dev/video4"' in pipeline
    assert "format=YUY2" in pipeline
    assert "max-buffers=1" in pipeline
    assert "jpegdec" not in pipeline


def test_mjpeg_pipeline_decodes_before_yuy2():
    pipeline = build_gstreamer_pipeline(camera("MJPEG"), "/dev/video4")
    assert "image/jpeg" in pipeline
    assert "jpegdec" in pipeline
    assert pipeline.index("jpegdec") < pipeline.index("format=YUY2")


def test_frame_validation_rejects_shape_and_non_contiguous():
    config = replace(camera(), width=16, height=8)
    valid = np.zeros((8, 16, 2), dtype=np.uint8)
    assert validate_yuyv_frame(valid, config) is valid
    with pytest.raises(CameraError, match="shape"):
        validate_yuyv_frame(np.zeros((8, 16, 3), dtype=np.uint8), config)
    with pytest.raises(CameraError, match="strides"):
        validate_yuyv_frame(valid[:, ::-1], config)
