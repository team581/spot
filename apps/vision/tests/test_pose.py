from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from spot_vision.config import Calibration, CameraConfig, CameraSelector, DetectorConfig
from spot_vision.models import Detection, PoseCandidate, PoseMethod, PoseSolution
from spot_vision.pose import (
    NWU_FROM_OPENCV,
    TAG_NWU_FROM_OPENCV,
    FieldLayout,
    FieldTag,
    PoseSolver,
    _rpy_matrix,
    _tag_plane_to_field,
    matrix_to_quaternion,
    quaternion_to_matrix,
    robot_from_camera_transform,
    select_robot_pose,
)

CALIBRATION = Calibration(
    camera_id="front",
    width=1280,
    height=800,
    pixel_format="YUY2",
    camera_matrix=((900, 0, 640), (0, 900, 400), (0, 0, 1)),
    distortion=(0, 0, 0, 0, 0),
)


def corners(size=0.1651):
    half = size / 2
    return np.array(
        [[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]], dtype=np.float64
    )


def detection(tag_id, object_points, rvec, tvec):
    image = cv2.projectPoints(
        object_points,
        rvec,
        tvec,
        np.asarray(CALIBRATION.camera_matrix),
        np.asarray(CALIBRATION.distortion),
    )[0].reshape(4, 2)
    return Detection(tag_id, image, 0, 100.0)


def transform(rotation, translation):
    value = np.eye(4)
    value[:3, :3] = rotation
    value[:3, 3] = translation
    return value


def camera_projection(field_from_camera):
    opencv_from_nwu = transform(NWU_FROM_OPENCV.T, np.zeros(3))
    camera_from_field = opencv_from_nwu @ np.linalg.inv(field_from_camera)
    return cv2.Rodrigues(camera_from_field[:3, :3])[0], camera_from_field[:3, 3]


def test_quaternion_matrix_round_trip():
    original = np.array([0.9238795, 0, 0, 0.3826834])
    recovered = matrix_to_quaternion(quaternion_to_matrix(original))
    assert np.allclose(recovered, original / np.linalg.norm(original), atol=1e-6)


def test_single_tag_preserves_two_ippe_candidates():
    field_from_tag = transform(np.eye(3), np.array([0.0, 0.0, 0.5]))
    layout = FieldLayout({1: FieldTag(1, field_from_tag)}, 9)
    solver = PoseSolver(CALIBRATION, layout, 0.1651)
    field_from_camera = transform(_rpy_matrix((2.0, -3.0, 177.0)), [2.5, 0.1, 0.6])
    rvec, tvec = camera_projection(field_from_camera)
    observed = detection(1, _tag_plane_to_field(field_from_tag, corners()), rvec, tvec)
    result = solver.solve((observed,))
    assert len(result.candidates) == 2
    assert all(
        candidate.method == PoseMethod.SINGLE_TAG_IPPE_SQUARE for candidate in result.candidates
    )
    assert result.used_tag_ids == {1}
    assert min(candidate.reprojection_error_px for candidate in result.candidates) < 1e-4
    selected = min(result.candidates, key=lambda candidate: candidate.reprojection_error_px)
    assert np.allclose(selected.translation, field_from_camera[:3, 3], atol=1e-5)
    assert np.allclose(
        quaternion_to_matrix(selected.quaternion_wxyz), field_from_camera[:3, :3], atol=1e-5
    )


def test_multi_tag_sq_pnp_recovers_field_from_camera():
    tag1 = transform(_rpy_matrix((0.0, 0.0, 0.0)), [0.0, -0.5, 0.5])
    tag2 = transform(_rpy_matrix((0.0, 0.0, 8.0)), [0.0, 0.5, 0.7])
    layout = FieldLayout({1: FieldTag(1, tag1), 2: FieldTag(2, tag2)}, 10)
    field_from_camera = transform(_rpy_matrix((1.0, -2.0, 178.0)), [3.0, 0.1, 0.6])
    rvec, tvec = camera_projection(field_from_camera)
    detections = []
    for tag_id, tag_transform in ((1, tag1), (2, tag2)):
        field = _tag_plane_to_field(tag_transform, corners())
        detections.append(detection(tag_id, field, rvec, tvec))
    result = PoseSolver(CALIBRATION, layout, 0.1651).solve(tuple(detections))
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.method == PoseMethod.MULTI_TAG_SQPNP
    assert np.allclose(candidate.translation, field_from_camera[:3, 3], atol=1e-5)
    assert np.allclose(
        quaternion_to_matrix(candidate.quaternion_wxyz), field_from_camera[:3, :3], atol=1e-5
    )
    assert candidate.reprojection_error_px < 1e-4
    assert candidate.tag_ids == (1, 2)


def test_image_rotation_and_mount_transform_recover_robot_pose():
    camera = CameraConfig(
        "front",
        True,
        CameraSelector(device="/dev/video0"),
        "YUY2",
        1280,
        800,
        60,
        None,
        0,
        DetectorConfig(),
        image_rotation_deg=180,
        robot_from_camera_translation=(0.0, 0.1, 0.0),
        robot_from_camera_rpy_deg=(0.0, -20.0, 0.0),
    )
    raw_calibration = replace(
        CALIBRATION,
        camera_matrix=((901.0, 0.0, 637.2), (0.0, 897.0, 391.4), (0.0, 0.0, 1.0)),
        distortion=(0.03, -0.01, 0.001, -0.002, 0.001),
    )
    rotated_calibration = raw_calibration.for_image_rotation(camera)
    tag1 = transform(np.eye(3), [0.0, -0.5, 0.5])
    tag2 = transform(_rpy_matrix((0.0, 0.0, 8.0)), [0.0, 0.5, 0.7])
    layout = FieldLayout({1: FieldTag(1, tag1), 2: FieldTag(2, tag2)}, 10)
    robot_from_corrected = robot_from_camera_transform(
        camera.robot_from_camera_translation, camera.robot_from_camera_rpy_deg
    )
    field_from_robot = transform(_rpy_matrix((1.0, -2.0, 178.0)), [3.0, 0.1, 0.6])
    # The raw sensor is physically rolled relative to the corrected virtual frame.
    field_from_raw = (
        field_from_robot
        @ robot_from_corrected
        @ transform(_rpy_matrix((180.0, 0.0, 0.0)), [0.0, 0.0, 0.0])
    )
    rvec, tvec = camera_projection(field_from_raw)
    observations = []
    for tag_id, tag in ((1, tag1), (2, tag2)):
        object_points = _tag_plane_to_field(tag, corners())
        raw_pixels = cv2.projectPoints(
            object_points,
            rvec,
            tvec,
            np.asarray(raw_calibration.camera_matrix),
            np.asarray(raw_calibration.distortion),
        )[0].reshape(4, 2)
        observations.append(
            Detection(tag_id, np.array([camera.width - 1, camera.height - 1]) - raw_pixels)
        )
    solution = PoseSolver(rotated_calibration, layout, 0.1651).solve(tuple(observations))
    robot_pose = select_robot_pose(solution, robot_from_corrected)
    assert robot_pose is not None
    assert robot_pose.reprojection_error_px < 1e-4
    assert np.allclose(robot_pose.translation, field_from_robot[:3, 3], atol=1e-4)
    assert np.allclose(
        quaternion_to_matrix(robot_pose.quaternion_wxyz), field_from_robot[:3, :3], atol=1e-4
    )


def test_tag_plane_is_rigid_and_uses_wpilib_yz_corner_order():
    assert np.allclose(TAG_NWU_FROM_OPENCV.T @ TAG_NWU_FROM_OPENCV, np.eye(3))
    assert np.linalg.det(TAG_NWU_FROM_OPENCV) == 1.0
    actual = _tag_plane_to_field(np.eye(4), corners(size=2.0))
    assert np.allclose(
        actual,
        [
            [0.0, -1.0, -1.0],
            [0.0, 1.0, -1.0],
            [0.0, 1.0, 1.0],
            [0.0, -1.0, 1.0],
        ],
    )


def test_multi_tag_solve_passes_all_known_corners_to_both_stages(monkeypatch):
    tag1 = transform(np.eye(3), [0.0, -0.4, 0.5])
    tag2 = transform(np.eye(3), [0.0, 0.4, 0.5])
    layout = FieldLayout({1: FieldTag(1, tag1), 2: FieldTag(2, tag2)}, 10)
    field_from_camera = transform(_rpy_matrix((0.0, 0.0, 180.0)), [3.0, 0.0, 0.5])
    rvec, tvec = camera_projection(field_from_camera)
    detections = tuple(
        detection(tag_id, _tag_plane_to_field(tag, corners()), rvec, tvec)
        for tag_id, tag in ((1, tag1), (2, tag2))
    )
    original_generic = cv2.solvePnPGeneric
    original_refine = cv2.solvePnP
    seen = []

    def capture_generic(objects, images, *args, **kwargs):
        seen.append(("initial", objects.copy(), images.copy()))
        return original_generic(objects, images, *args, **kwargs)

    def capture_refine(objects, images, *args, **kwargs):
        seen.append(("refine", objects.copy(), images.copy()))
        return original_refine(objects, images, *args, **kwargs)

    monkeypatch.setattr(cv2, "solvePnPGeneric", capture_generic)
    monkeypatch.setattr(cv2, "solvePnP", capture_refine)
    result = PoseSolver(CALIBRATION, layout, 0.1651).solve(detections)
    assert len(result.candidates) == 1
    assert [stage for stage, _, _ in seen] == ["initial", "refine"]
    assert all(objects.shape == (8, 3) and images.shape == (8, 2) for _, objects, images in seen)
    assert np.array_equal(seen[0][1], seen[1][1])
    assert np.array_equal(seen[0][2], seen[1][2])


def test_failed_multi_tag_solve_does_not_fall_back_to_single(monkeypatch):
    layout = FieldLayout({tag_id: FieldTag(tag_id, np.eye(4)) for tag_id in (1, 2)}, 10)
    solver = PoseSolver(CALIBRATION, layout, 0.1651)
    monkeypatch.setattr(solver, "_solve_multi", lambda detections: ())

    def unexpected_single(_detection):
        raise AssertionError("multi-tag solve must not fall back to single-tag")

    monkeypatch.setattr(solver, "_solve_single", unexpected_single)
    detections = tuple(Detection(tag_id, np.zeros((4, 2))) for tag_id in (1, 2))
    result = solver.solve(detections)
    assert result.candidates == ()
    assert result.used_tag_ids == frozenset()


def test_robot_extrinsic_is_applied_after_camera_candidate_selection():
    field_from_robot = transform(_rpy_matrix((3.0, -4.0, 35.0)), [4.0, 2.0, 0.2])
    robot_from_camera = robot_from_camera_transform((0.0, 0.1, 0.0), (0.0, -20.0, 0.0))
    field_from_camera = field_from_robot @ robot_from_camera
    camera_candidate = PoseCandidate(
        PoseMethod.SINGLE_TAG_IPPE_SQUARE,
        field_from_camera[:3, 3],
        matrix_to_quaternion(field_from_camera[:3, :3]),
        0.1,
        (1,),
    )
    worse_candidate = PoseCandidate(
        PoseMethod.SINGLE_TAG_IPPE_SQUARE,
        np.array([100.0, 100.0, 100.0]),
        np.array([1.0, 0.0, 0.0, 0.0]),
        0.2,
        (1,),
    )
    selected = select_robot_pose(
        PoseSolution((worse_candidate, camera_candidate)), robot_from_camera
    )
    assert selected is not None
    assert np.allclose(selected.translation, field_from_robot[:3, 3], atol=1e-9)
    assert np.allclose(
        quaternion_to_matrix(selected.quaternion_wxyz), field_from_robot[:3, :3], atol=1e-9
    )


def test_unknown_and_missing_inputs_keep_raw_rejection_reasons():
    observed = Detection(99, np.zeros((4, 2)))
    assert (
        PoseSolver(None, None, 0.1651).solve((observed,)).rejection_reasons[99] == "NO_CALIBRATION"
    )
    result = PoseSolver(CALIBRATION, FieldLayout({}, 1), 0.1651).solve((observed,))
    assert result.rejection_reasons[99] == "UNKNOWN_TAG_ID"
