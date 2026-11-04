import math
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from spot_vision.config import load_calibration
from spot_vision.uncertainty import distortion_factors, standard_deviations

DATA = Path(__file__).parent / "data" / "regression"


def test_distortion_factor_matches_independent_forward_projection():
    calibration = load_calibration(DATA / "calibration.json")
    matrix = np.asarray(calibration.camera_matrix)
    ideal = np.array(
        [
            [[610.0, 370.0], [670.0, 370.0], [670.0, 430.0], [610.0, 430.0]],
            [[1000.0, 200.0], [1100.0, 200.0], [1100.0, 300.0], [1000.0, 300.0]],
        ]
    )
    normalized = np.column_stack(
        ((ideal.reshape(-1, 2) - matrix[:2, 2]) / np.diag(matrix)[:2], np.ones(8))
    )
    raw = cv2.projectPoints(
        normalized, np.zeros(3), np.zeros(3), matrix, np.asarray(calibration.distortion)
    )[0].reshape(2, 4, 2)
    factors = distortion_factors(raw, calibration)
    expected = np.linalg.norm(raw - ideal, axis=2).mean(axis=1)
    assert np.allclose(factors, expected, atol=1e-6)
    assert factors[1] > factors[0] * 10
    assert np.allclose(distortion_factors(ideal, replace(calibration, distortion=(0,) * 5)), 0)
    assert distortion_factors(np.empty((0, 4, 2)), calibration).size == 0


def test_uncertainty_inflates_distance_model_without_resolving_heading():
    tuning = {
        "camera_factor": 1.5,
        "xy_coefficient": 0.02,
        "theta_coefficient": 0.03,
        "distortion_scalar": 0.01,
    }
    center = standard_deviations(3.0, 2, 0.0, **tuning)
    edge = standard_deviations(3.0, 2, 50.0, **tuning)
    assert edge[0] == pytest.approx(center[0] * 2.25)
    assert edge[0] == edge[1]
    assert math.isinf(edge[2])
    assert standard_deviations(3.0, 2, 50.0, heading_resolved=True, **tuning)[2] == pytest.approx(
        edge[0] * 1.5
    )
    assert standard_deviations(3.0, 1, 0.0, **tuning)[0] == pytest.approx(center[0] * 4)


@pytest.mark.parametrize(
    "distance,count,factor", [(float("nan"), 1, 0), (3, 0, 0), (3, 1, -1), (3, True, 0)]
)
def test_invalid_uncertainty_inputs_are_rejected(distance, count, factor):
    with pytest.raises(ValueError):
        standard_deviations(
            distance,
            count,
            factor,
            camera_factor=1,
            xy_coefficient=1,
            theta_coefficient=1,
            distortion_scalar=0.01,
        )
