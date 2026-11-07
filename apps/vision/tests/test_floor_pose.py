"""Flat-robot pose recovery with pitched mounts and the captured trench failure."""

import json
from pathlib import Path

import numpy as np
import pytest

from spot_vision.config import Calibration
from spot_vision.models import Detection, PoseMethod
from spot_vision.pose import (
    MAX_ROBOT_HEIGHT_M,
    FieldLayout,
    FieldTag,
    PoseSolver,
    _rpy_matrix,
    _tag_plane_to_field,
    quaternion_to_matrix,
    robot_from_camera_transform,
    select_robot_pose,
)
from test_pose import CALIBRATION, camera_projection, corners, detection, transform

TRENCH_TAGS = {29: 0.6659626, 30: 1.0977626}


def synthetic(ids, mount, truth):
    tags = {
        tag_id: FieldTag(tag_id, transform(np.eye(3), [0, y, 0.55245]))
        for tag_id, y in TRENCH_TAGS.items()
        if tag_id in ids
    }
    rvec, tvec = camera_projection(truth @ mount)
    observed = tuple(
        detection(tag_id, _tag_plane_to_field(tag.field_from_tag, corners()), rvec, tvec)
        for tag_id, tag in tags.items()
    )
    return PoseSolver(CALIBRATION, FieldLayout(tags, 1), 0.1651, mount).solve(observed)


@pytest.mark.parametrize("height_m", [0.0, 0.1])
@pytest.mark.parametrize("ids", [(29,), (29, 30)])
@pytest.mark.parametrize("mount_rpy", [(0, -20, 180), (7, -15, 155)])
def test_flat_robot_recovers_position_height_and_yaw(ids, mount_rpy, height_m):
    mount = robot_from_camera_transform((-0.318389, 0.08255, 0.342468), mount_rpy)
    truth = transform(_rpy_matrix((0, 0, 12)), [4.5, 0.8, height_m])
    robot = select_robot_pose(synthetic(ids, mount, truth), mount)
    assert robot.method == (
        PoseMethod.SINGLE_TAG_IPPE_SQUARE if len(ids) == 1 else PoseMethod.MULTI_TAG_SQPNP
    )
    assert robot.tag_ids == ids
    assert robot.reprojection_error_px < 1e-6
    assert np.allclose(robot.translation, truth[:3, 3], atol=1e-6)
    assert np.allclose(quaternion_to_matrix(robot.quaternion_wxyz), truth[:3, :3], atol=1e-6)


def test_robot_above_height_limit_is_clamped_and_leaves_a_large_residual():
    # Consumers rely on the residual to reject frames the floor model cannot explain.
    mount = robot_from_camera_transform((-0.318389, 0.08255, 0.342468), (0, -20, 180))
    truth = transform(np.eye(3), [4.5, 0.8, 0.5])
    robot = select_robot_pose(synthetic((29, 30), mount, truth), mount)
    assert robot.translation[2] == pytest.approx(MAX_ROBOT_HEIGHT_M)
    assert robot.reprojection_error_px > 5


def trench():
    data = json.loads((Path(__file__).parent / "data/trench-floor.json").read_text())
    intrinsics = data["intrinsics"]
    calibration = Calibration(
        camera_id="back",
        width=640,
        height=480,
        pixel_format="MJPEG",
        camera_matrix=tuple(tuple(row) for row in intrinsics["camera_matrix"]),
        distortion=tuple(intrinsics["distortion_coefficients"]),
    )
    layout = FieldLayout(
        {
            tag_id: FieldTag(tag_id, transform(np.eye(3), [0.007747, y, 0.55245]))
            for tag_id, y in TRENCH_TAGS.items()
        },
        1,
    )
    m = data["mount"]
    mount = robot_from_camera_transform(
        (m["x_m"], m["y_m"], m["z_m"]), (m["roll_deg"], m["pitch_deg"], m["yaw_deg"])
    )
    return data, PoseSolver(calibration, layout, 0.1651, mount), mount


@pytest.mark.parametrize(("frame", "tolerance_m"), [("tags", 0.15), ("single_tag", 0.5)])
def test_recorded_trench_frames_solve_flat_on_the_floor(frame, tolerance_m):
    # Unconstrained, the two-tag frame put the robot 0.8 m below the floor.
    data, solver, mount = trench()
    observed = tuple(Detection(tag["id"], np.asarray(tag["corners"])) for tag in data[frame])
    solution = solver.solve(observed)
    robot = select_robot_pose(solution, mount)
    assert robot.translation[2] == pytest.approx(0, abs=0.02)
    assert np.allclose(quaternion_to_matrix(robot.quaternion_wxyz)[:, 2], [0, 0, 1], atol=1e-9)
    assert robot.reprojection_error_px < 1
    # Reference from the gyro heading; without it, heading error shifts a far single tag sideways.
    assert np.linalg.norm(robot.translation[:2] - [4.572, 0.566]) < tolerance_m
    assert solution.used_tag_ids == {tag["id"] for tag in data[frame]}
    assert np.sqrt(
        np.mean([d["error_px"] ** 2 for d in solution.tag_diagnostics.values()])
    ) == pytest.approx(robot.reprojection_error_px)
