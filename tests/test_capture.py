from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from spot_vision import capture
from spot_vision.capture import (
    CameraError,
    bgr_to_yuyv_frame,
    build_gstreamer_pipeline,
    configure_controls,
    orient_yuyv_frame,
    validate_yuyv_frame,
)
from spot_vision.config import CameraConfig, CameraSelector, DetectorConfig


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


def test_bgr_fallback_converts_to_packed_yuyv():
    cv2 = pytest.importorskip("cv2")
    configured = camera("MJPEG")
    frame = np.zeros((configured.height, configured.width, 3), dtype=np.uint8)
    converted = bgr_to_yuyv_frame(frame, configured, cv2)
    assert converted.shape == (configured.height, configured.width, 2)
    assert converted.dtype == np.uint8


def test_manual_exposure_converts_microseconds_to_uvc_units(monkeypatch):
    calls = []

    def record_control(device, name, value):
        calls.append((device, name, value))
        return True

    monkeypatch.setattr(capture, "_set_control", record_control)
    configure_controls(camera(), "/dev/video4")
    assert ("/dev/video4", "exposure_time_absolute", 10) in calls
    assert ("/dev/video4", "gain", 20) in calls


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
    raw = np.array([
        [[10, 101], [20, 201], [30, 102], [40, 202]],
        [[50, 103], [60, 203], [70, 104], [80, 204]],
    ], dtype=np.uint8)
    oriented = orient_yuyv_frame(raw, configured)
    assert oriented.tolist() == [
        [[80, 104], [70, 204], [60, 103], [50, 203]],
        [[40, 102], [30, 202], [20, 101], [10, 201]],
    ]
    assert validate_yuyv_frame(oriented, configured) is oriented
    assert np.array_equal(orient_yuyv_frame(oriented, configured), raw)
    assert orient_yuyv_frame(raw, replace(configured, image_rotation_deg=0)) is raw
