from __future__ import annotations

import cv2
import numpy as np

from buddy_vision.config import Calibration
from buddy_vision.models import Detection, PoseMethod
from buddy_vision.pose import (
    FieldLayout,
    FieldTag,
    PoseSolver,
    matrix_to_quaternion,
    quaternion_to_matrix,
)

CALIBRATION = Calibration(
    camera_id="front", width=1280, height=800, pixel_format="YUY2",
    camera_matrix=((900, 0, 640), (0, 900, 400), (0, 0, 1)),
    distortion=(0, 0, 0, 0, 0),
)


def corners(size=0.1651):
    half = size / 2
    return np.array([[-half, half, 0], [half, half, 0],
                     [half, -half, 0], [-half, -half, 0]], dtype=np.float64)


def detection(tag_id, object_points, rvec, tvec):
    image = cv2.projectPoints(object_points, rvec, tvec,
                              np.asarray(CALIBRATION.camera_matrix),
                              np.asarray(CALIBRATION.distortion))[0].reshape(4, 2)
    return Detection(tag_id, image, 0, 100.0)


def test_quaternion_matrix_round_trip():
    original = np.array([0.9238795, 0, 0, 0.3826834])
    recovered = matrix_to_quaternion(quaternion_to_matrix(original))
    assert np.allclose(recovered, original / np.linalg.norm(original), atol=1e-6)


def test_single_tag_preserves_two_ippe_candidates():
    layout = FieldLayout({1: FieldTag(1, np.eye(4))}, 9)
    solver = PoseSolver(CALIBRATION, layout, 0.1651)
    observed = detection(1, corners(), np.zeros((3, 1)), np.array([[0.02], [0.01], [2.0]]))
    result = solver.solve((observed,))
    assert len(result.candidates) == 2
    assert all(candidate.method == PoseMethod.SINGLE_TAG_IPPE_SQUARE
               for candidate in result.candidates)
    assert result.used_tag_ids == {1}
    assert min(candidate.reprojection_error_px for candidate in result.candidates) < 1e-4


def test_multi_tag_sq_pnp_recovers_field_from_camera():
    tag1 = np.eye(4)
    tag1[0, 3] = -0.5
    tag2 = np.eye(4)
    tag2[0, 3] = 0.5
    layout = FieldLayout({1: FieldTag(1, tag1), 2: FieldTag(2, tag2)}, 10)
    rvec = np.zeros((3, 1))
    tvec = np.array([[0.0], [0.0], [3.0]])
    detections = []
    for tag_id, transform in ((1, tag1), (2, tag2)):
        local = corners()
        field = (transform @ np.column_stack((local, np.ones(4))).T).T[:, :3]
        detections.append(detection(tag_id, field, rvec, tvec))
    result = PoseSolver(CALIBRATION, layout, 0.1651).solve(tuple(detections))
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.method == PoseMethod.MULTI_TAG_SQPNP
    assert np.allclose(candidate.translation, [0, 0, -3], atol=1e-5)
    assert candidate.reprojection_error_px < 1e-4


def test_unknown_and_missing_inputs_keep_raw_rejection_reasons():
    observed = Detection(99, np.zeros((4, 2)))
    assert PoseSolver(None, None, 0.1651).solve((observed,)).rejection_reasons[99] == "NO_CALIBRATION"
    result = PoseSolver(CALIBRATION, FieldLayout({}, 1), 0.1651).solve((observed,))
    assert result.rejection_reasons[99] == "UNKNOWN_TAG_ID"
