"""Validate the parts of a stored/imported calibration record the runtime uses."""

from __future__ import annotations

from .config import ConfigError


def validate_record(record: dict) -> None:
    try:
        if any(
            not isinstance(record.get(key), str) or not 1 <= len(record[key]) <= 128
            for key in ("identity", "mode_signature")
        ):
            raise ConfigError("Calibration identity and optical signature must be bounded text")
        intrinsics = record["intrinsics"]
        matrix = intrinsics["camera_matrix"]
        if len(matrix) != 3 or any(len(row) != 3 for row in matrix) or matrix[2] != [0, 0, 1]:
            raise ConfigError("Calibration camera matrix must be canonical 3×3")
        if any(
            type(intrinsics[key]) is not int or not 16 <= intrinsics[key] <= 8192
            for key in ("width", "height")
        ):
            raise ConfigError("Calibration dimensions must be bounded integers")
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"Incomplete or invalid calibration record: {exc}") from exc
