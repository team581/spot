"""Validate stored/imported quality evidence, not just a browser pass flag."""

from __future__ import annotations

import math

from .charuco import CharucoBoardConfig
from .config import ConfigError


def validate_record(record: dict) -> None:
    try:
        if any(
            not isinstance(record.get(key), str) or not 1 <= len(record[key]) <= 128
            for key in ("identity", "mode_signature")
        ):
            raise ConfigError("Calibration identity and optical signature must be bounded text")
        fit, holdout, intrinsics = record["fit"], record["holdout"], record["intrinsics"]
        if record["algorithm"] != "charuco-fit-holdout-v2" or record["model"] not in {
            "plumb_bob",
            "rational",
        }:
            raise ConfigError("Unsupported calibration algorithm/model")
        board = CharucoBoardConfig(**record["board"])
        board.validate()
        if board.squares_x > 40 or board.squares_y > 40:
            raise ConfigError("Calibration board exceeds bounds")
        if (
            fit.get("accepted") is not True
            or holdout.get("accepted") is not True
            or intrinsics.get("provisional", False)
        ):
            raise ConfigError("Provisional or unvalidated calibration")
        if (
            type(fit["frames_used"]) is not int
            or not 15 <= fit["frames_used"] <= 80
            or type(holdout["views"]) is not int
            or not 5 <= holdout["views"] <= 20
        ):
            raise ConfigError("Insufficient bounded fitting/validation view counts")
        for value in (
            fit["rms_reprojection_error_px"],
            holdout["rms_px"],
            intrinsics["reprojection_error_px"],
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 0.8:
                raise ConfigError("Calibration RMS does not meet the production limit")
        if not 0.35 <= fit["coverage"] <= 1 or not 0.55 <= fit["diversity"] <= 1:
            raise ConfigError("Calibration coverage/diversity is insufficient")
        matrix = intrinsics["camera_matrix"]
        if len(matrix) != 3 or any(len(row) != 3 for row in matrix) or matrix[2] != [0, 0, 1]:
            raise ConfigError("Calibration camera matrix must be canonical 3×3")
        if len(intrinsics["distortion_coefficients"]) != (
            5 if record["model"] == "plumb_bob" else 14
        ):
            raise ConfigError("Calibration coefficient count does not match the fitting model")
        if (
            any(
                type(value) not in (float, int) or not math.isfinite(value)
                for value in [v for row in matrix for v in row]
                + intrinsics["distortion_coefficients"]
            )
            or matrix[0][0] <= 0
            or matrix[1][1] <= 0
            or any(
                type(intrinsics[key]) is not int or not 16 <= intrinsics[key] <= 8192
                for key in ("width", "height")
            )
        ):
            raise ConfigError(
                "Calibration intrinsics must be finite with positive focal lengths and bounded dimensions"
            )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"Incomplete or invalid calibration evidence: {exc}") from exc
