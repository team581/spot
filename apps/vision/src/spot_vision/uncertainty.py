"""Distortion diagnostics and the tunable model used by pose-estimator consumers."""

from __future__ import annotations

import math

import numpy as np

from .config import Calibration


def distortion_factors(corners: np.ndarray, calibration: Calibration) -> np.ndarray:
    """Mean raw-to-ideal pixel displacement for each four-corner tag.

    Corners stay in the raw (orientation-corrected) image frame. This operation
    measures distortion; it does not replace the points passed to solvePnP.
    """
    import cv2

    raw = np.asarray(corners, dtype=np.float64).reshape(-1, 4, 2)
    if not len(raw):
        return np.empty(0, dtype=np.float64)
    matrix = np.asarray(calibration.camera_matrix, dtype=np.float64)
    criteria = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-9)
    if hasattr(cv2, "undistortPointsIter"):
        ideal = cv2.undistortPointsIter(
            raw.reshape(-1, 1, 2),
            matrix,
            np.asarray(calibration.distortion),
            None,
            matrix,
            criteria,
        )
    else:  # OpenCV 5 merged the iterative overload into undistortPoints.
        ideal = cv2.undistortPoints(
            raw.reshape(-1, 1, 2),
            matrix,
            np.asarray(calibration.distortion),
            P=matrix,
            criteria=criteria,
        )
    ideal = ideal.reshape(-1, 4, 2)
    factors = np.linalg.norm(raw - ideal, axis=2).mean(axis=1)
    if not np.all(np.isfinite(factors)):
        raise ValueError("non-finite distortion factor")
    return factors


def standard_deviations(
    average_tag_distance_m: float,
    tag_count: int,
    distortion_factor_px: float,
    *,
    camera_factor: float,
    xy_coefficient: float,
    theta_coefficient: float,
    distortion_scalar: float,
    heading_resolved: bool = False,
) -> tuple[float, float, float]:
    """Return (x metres, y metres, theta radians) with explicit consumer tuning.

    distortion_scalar has units 1/pixel. No team-specific coefficients are
    assumed. Unresolved heading remains infinite, including ambiguous IPPE.
    """
    values = (
        average_tag_distance_m,
        distortion_factor_px,
        camera_factor,
        xy_coefficient,
        theta_coefficient,
        distortion_scalar,
    )
    if (
        type(tag_count) is not int
        or tag_count < 1
        or any(not math.isfinite(value) or value < 0 for value in values)
    ):
        raise ValueError("uncertainty requires a positive tag count and finite nonnegative inputs")
    scale = (
        camera_factor
        * (average_tag_distance_m * (1 + distortion_scalar * distortion_factor_px)) ** 2
        / tag_count**2
    )
    return (
        xy_coefficient * scale,
        xy_coefficient * scale,
        theta_coefficient * scale if heading_resolved else math.inf,
    )
