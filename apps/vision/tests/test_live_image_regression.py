"""Permanent offline regressions from all four real alpha camera images."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from spot_vision import _spot_cuda as native

DATA = Path(__file__).parent / "data/live-alpha"


@pytest.mark.parametrize(
    "camera_id,width,height",
    [("1", 640, 480), ("2", 1280, 720), ("3", 1280, 720), ("4", 1280, 720)],
)
def test_real_tag4_image_detection_is_repeatable_and_does_not_leave_stale_tags(
    camera_id, width, height
):
    image = cv2.imread(str(DATA / f"camera-{camera_id}.jpg"))
    assert image is not None and image.shape == (height, width, 3)
    yuyv = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_YUY2)
    original = yuyv.copy()
    detector = native.CpuDetector(width, height, native.DetectorOptions())
    first = detector.detect(yuyv)
    assert [tag.id for tag in first.detections] == [4]
    tag = first.detections[0]
    corners = np.array(tag.corners)
    assert corners.shape == (4, 2) and np.isfinite(corners).all()
    assert ((corners >= 0) & (corners < [width, height])).all()
    assert 0 <= tag.hamming <= 2 and tag.decision_margin > 0
    # Corner winding must remain consistent on real camera data as well as the
    # exact synthetic fixtures. Compare repeats directly in canonical order.
    for _ in range(3):
        batch = detector.detect(yuyv)
        assert [tag.id for tag in batch.detections] == [4]
        assert np.allclose(batch.detections[0].corners, corners, atol=1e-5)
        assert batch.input_address == yuyv.ctypes.data
    assert not detector.detect(np.full_like(yuyv, 128)).detections
    detector.reset()
    assert detector.metrics().calls == 0
    assert [tag.id for tag in detector.detect(yuyv).detections] == [4]
    assert np.array_equal(yuyv, original)
