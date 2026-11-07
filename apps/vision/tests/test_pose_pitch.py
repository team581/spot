"""Pitch oracle using physical corners and FIRST-oriented tag artwork.

The projection intentionally does not use Spot's tag-plane or camera-basis
helpers: a self-consistent wrong basis would otherwise pass a round trip.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from spot_vision.config import Calibration, DetectorConfig
from spot_vision.models import Detection
from spot_vision.native import CpuDetector
from spot_vision.pose import FieldLayout, FieldTag, PoseSolver, quaternion_to_matrix

K = np.array([[900.0, 0.0, 640.0], [0.0, 900.0, 400.0], [0.0, 0.0, 1.0]])
SIZE = 0.3
CAMERA = np.array([2.0, -0.25, 0.5])
CALIBRATION = Calibration(
    camera_id="front",
    width=1280,
    height=800,
    pixel_format="YUY2",
    camera_matrix=tuple(tuple(row) for row in K),
    distortion=(0.0,) * 5,
)


def scene(pitch_deg, ids=(4,)):
    pitch = np.deg2rad(pitch_deg)
    c, s = np.cos(pitch), np.sin(pitch)
    # Camera faces field -X. Optical right = field +Y. Positive NWU pitch
    # tilts its forward axis down. These are camera axes written in field space.
    forward, left, up = [-c, 0.0, -s], [0.0, -1.0, 0.0], [-s, 0.0, c]
    rotation = np.column_stack((forward, left, up))
    optical_from_field = np.array([-np.array(left), -np.array(up), forward])
    tags, observations = {}, []
    for tag_id in ids:
        center = np.array([0.0, (tag_id - 4) * 0.5, 1.124])
        pose = np.eye(4)
        pose[:3, 3] = center
        tags[tag_id] = FieldTag(tag_id, pose)
        # FIRST-oriented decoded order: bottom left/right, top right/left.
        offsets = np.array(
            [
                [0.0, -SIZE / 2, -SIZE / 2],
                [0.0, SIZE / 2, -SIZE / 2],
                [0.0, SIZE / 2, SIZE / 2],
                [0.0, -SIZE / 2, SIZE / 2],
            ]
        )
        optical = (optical_from_field @ (center + offsets - CAMERA).T).T
        pixels = optical[:, :2] / optical[:, 2:] * [900.0, 900.0] + [640.0, 400.0]
        observations.append(Detection(tag_id, pixels))
    return FieldLayout(tags, 1), tuple(observations), rotation


def solver(layout, rotation):
    """Mount the camera on a flat robot facing field -X whose origin is below the camera."""
    field_from_robot = np.diag([-1.0, -1.0, 1.0, 1.0])
    field_from_robot[:2, 3] = CAMERA[:2]
    field_from_camera = np.eye(4)
    field_from_camera[:3, :3] = rotation
    field_from_camera[:3, 3] = CAMERA
    return PoseSolver(
        CALIBRATION, layout, SIZE, np.linalg.inv(field_from_robot) @ field_from_camera
    )


@pytest.mark.parametrize("ids", [(4,), (4, 5)])
@pytest.mark.parametrize("pitch_deg", [-25.0, -15.0, 0.0, 10.0])
def test_camera_pitch_and_height_from_independent_physical_scene(ids, pitch_deg):
    layout, observations, expected_rotation = scene(pitch_deg, ids)
    solution = solver(layout, expected_rotation).solve(observations)
    selected = min(solution.candidates, key=lambda p: p.reprojection_error_px)
    assert selected.reprojection_error_px < 1e-6
    assert np.allclose(selected.translation, CAMERA, atol=1e-6)
    assert np.allclose(quaternion_to_matrix(selected.quaternion_wxyz), expected_rotation, atol=1e-6)


@pytest.mark.parametrize("pitch_deg", [-25.0, -15.0, 0.0])
def test_native_first_tag_artwork_recovers_upright_camera_and_pitch(pitch_deg):
    layout, observations, expected_rotation = scene(pitch_deg)
    # Independent official artwork, not an ArUco image rotated to satisfy tests.
    artwork = cv2.imread(
        str(Path(__file__).parent / "data/regression/official-tag4.png"), cv2.IMREAD_GRAYSCALE
    )
    # The 10x10 source includes a one-pixel white margin around the 8x8 tag.
    marker = cv2.resize(artwork[1:-1, 1:-1], (240, 240), interpolation=cv2.INTER_NEAREST)
    homography = cv2.getPerspectiveTransform(
        np.array([[0, 0], [240, 0], [240, 240], [0, 240]], np.float32),
        observations[0].corners[[3, 2, 1, 0]].astype(np.float32),
    )
    image = cv2.warpPerspective(marker, homography, (1280, 800), borderValue=255)
    frame = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), cv2.COLOR_BGR2YUV_YUY2)
    batch = CpuDetector(1280, 800, DetectorConfig()).detect(frame)
    assert len(batch.detections) == 1 and batch.detections[0].id == 4
    detected = Detection(4, np.asarray(batch.detections[0].corners))
    assert np.max(np.linalg.norm(detected.corners - observations[0].corners, axis=1)) < 1.0
    solution = solver(layout, expected_rotation).solve((detected,))
    selected = min(solution.candidates, key=lambda p: p.reprojection_error_px)
    assert np.allclose(selected.translation, CAMERA, atol=0.04)
    assert np.allclose(quaternion_to_matrix(selected.quaternion_wxyz), expected_rotation, atol=0.02)


def test_tilting_camera_down_moves_tag_up_without_changing_camera_height():
    previous_center_y = float("inf")
    for pitch in [-25.0, -15.0, 0.0, 10.0]:
        layout, observations, rotation = scene(pitch)
        center_y = observations[0].corners[:, 1].mean()
        assert center_y < previous_center_y
        previous_center_y = center_y
        solution = solver(layout, rotation).solve(observations)
        selected = min(solution.candidates, key=lambda p: p.reprojection_error_px)
        assert selected.reprojection_error_px < 1e-6
        forward = quaternion_to_matrix(selected.quaternion_wxyz)[:, 0]
        assert np.isclose(forward[2], -np.sin(np.deg2rad(pitch)), atol=1e-6)
        assert np.isclose(selected.translation[2], CAMERA[2], atol=1e-6)
