"""Rotation singularities and backend failure diagnostics."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from spot_vision.config import ConfigError, load_calibration
from spot_vision.models import Detection, PoseCandidate, PoseMethod, PoseSolution
from spot_vision.pose import (FieldLayout, FieldTag, PoseSolver, matrix_to_quaternion,
                              quaternion_to_matrix, select_robot_pose)

DATA = Path(__file__).parent / "data/regression"


@pytest.mark.parametrize("axis", [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 2, 3]])
@pytest.mark.parametrize("angle", [np.pi, np.pi - 1e-8])
def test_quaternion_conversion_near_half_turn_preserves_rotation(axis, angle):
    vector = np.array(axis, dtype=float)
    rotation = cv2.Rodrigues(vector / np.linalg.norm(vector) * angle)[0]
    quaternion = matrix_to_quaternion(rotation)
    assert np.isfinite(quaternion).all()
    assert np.linalg.norm(quaternion) == pytest.approx(1)
    assert np.allclose(quaternion_to_matrix(quaternion), rotation, atol=1e-9)
    assert np.allclose(quaternion_to_matrix(-quaternion * 3), rotation, atol=1e-9)


def test_zero_quaternion_is_rejected():
    with pytest.raises(ConfigError, match="zero-length"):
        quaternion_to_matrix(np.zeros(4))


def test_pose_selection_has_stable_tie_break_and_validates_mount_shape():
    first = PoseCandidate(PoseMethod.SINGLE_TAG_IPPE_SQUARE, np.array([1, 2, 3]),
                          np.array([1, 0, 0, 0]), .2, (1,))
    second = PoseCandidate(PoseMethod.SINGLE_TAG_IPPE_SQUARE, np.array([9, 8, 7]),
                           np.array([1, 0, 0, 0]), .2, (1,))
    result = select_robot_pose(PoseSolution((first, second)), np.eye(4))
    assert np.array_equal(result.translation, first.translation)
    with pytest.raises(ConfigError, match="4x4"):
        select_robot_pose(PoseSolution((first,)), np.eye(3))
    assert select_robot_pose(PoseSolution(), np.eye(4)) is None


def test_solver_failure_retains_known_and_unknown_raw_observations(monkeypatch):
    solver = PoseSolver(load_calibration(DATA / "calibration.json"),
                        FieldLayout({1: FieldTag(1, np.eye(4))}, 1), .3)

    def fail(_):
        raise cv2.error("bad geometry")

    monkeypatch.setattr(solver, "_solve_single", fail)
    solution = solver.solve(tuple(Detection(tag_id, np.zeros((4, 2))) for tag_id in [1, 99]))
    assert not solution.candidates and not solution.used_tag_ids
    assert solution.rejection_reasons == {1: "POSE_SOLVE_FAILED:error", 99: "UNKNOWN_TAG_ID"}
    assert solution.solve_ms >= 0


@pytest.mark.parametrize("content", [[], {"tags": None}, {"tags": {}}])
def test_field_layout_rejects_missing_tag_array(tmp_path, content):
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(content))
    with pytest.raises(ConfigError, match="tags array"):
        FieldLayout.load(path)


def test_field_layout_rejects_duplicate_ids_and_respects_explicit_revision(tmp_path):
    raw = json.loads((DATA / "layout.json").read_text())
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(raw))
    assert FieldLayout.load(path, 123).revision == 123
    raw["tags"].append(raw["tags"][0])
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="duplicate field tag"):
        FieldLayout.load(path)
