"""ChArUco calibration primitives used by the local calibration wizard."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class CharucoBoardConfig:
    squares_x: int = 15
    squares_y: int = 15
    square_length_m: float = 0.03
    marker_length_m: float = 0.022
    dictionary: str = "DICT_4X4_250"

    def validate(self) -> None:
        if self.squares_x < 2 or self.squares_y < 2:
            raise ValueError("board must contain at least 2 x 2 squares")
        if self.marker_length_m <= 0 or self.square_length_m <= self.marker_length_m:
            raise ValueError("marker length must be positive and smaller than square length")


@dataclass(frozen=True)
class CalibrationOptions:
    model: str = "plumb_bob"
    min_charuco_corners: int = 12
    min_markers: int = 4
    min_frames: int = 15
    min_coverage: float = 0.35
    min_diversity: float = 0.55
    max_rms_px: float = 0.8
    outlier_mad_scale: float = 3.0
    max_frames: int = 80
    min_frame_motion: float = 0.025

    def validate(self) -> None:
        if self.model not in {"plumb_bob", "rational"}:
            raise ValueError("model must be plumb_bob or rational")
        if self.min_frames < 3 or self.min_charuco_corners < 4:
            raise ValueError("calibration thresholds are too small")
        if self.max_frames < self.min_frames or not 0 < self.min_frame_motion < 1:
            raise ValueError("invalid frame limit or capture motion threshold")


@dataclass
class CharucoFrame:
    image_points: np.ndarray
    ids: np.ndarray
    image_size: tuple[int, int]
    marker_count: int
    coverage: float = 0.0
    sharpness: float = 0.0
    quality: float = 0.0
    reprojection_error_px: float | None = None


@dataclass(frozen=True)
class CalibrationReport:
    accepted: bool
    reason: str
    frames_used: int
    coverage: float
    diversity: float
    rms_reprojection_error_px: float | None
    rejected_frames: int = 0


def _aruco():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("ChArUco calibration requires opencv-contrib-python") from exc
    if not hasattr(cv2, "aruco"):
        raise RuntimeError("ChArUco calibration requires opencv-contrib-python")
    return cv2


def make_board(config: CharucoBoardConfig):
    cv2 = _aruco()
    config.validate()
    dictionary_id = getattr(cv2.aruco, config.dictionary, None)
    if dictionary_id is None:
        raise ValueError(f"unknown ArUco dictionary {config.dictionary!r}")
    dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
    required = config.squares_x * config.squares_y // 2
    if required > len(dictionary.bytesList):
        raise ValueError(
            f"{config.squares_x} x {config.squares_y} board needs {required} unique markers; "
            f"{config.dictionary} only has {len(dictionary.bytesList)}. "
            "Choose the larger dictionary used to print the board."
        )
    try:
        return cv2.aruco.CharucoBoard(
            (config.squares_x, config.squares_y),
            config.square_length_m,
            config.marker_length_m,
            dictionary,
        )
    except TypeError:  # OpenCV 4.6 compatibility
        return cv2.aruco_CharucoBoard_create(
            config.squares_x,
            config.squares_y,
            config.square_length_m,
            config.marker_length_m,
            dictionary,
        )


def detect_frame(
    image: np.ndarray, board_config: CharucoBoardConfig, options: CalibrationOptions
) -> CharucoFrame | None:
    cv2 = _aruco()
    board = make_board(board_config)
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dictionary = board.getDictionary()
    params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(dictionary, params)
    marker_corners, marker_ids, _ = detector.detectMarkers(gray)
    marker_count = 0 if marker_ids is None else len(marker_ids)
    if marker_count < options.min_markers:
        return None
    if hasattr(cv2.aruco, "CharucoDetector"):
        corners, ids, _, _ = cv2.aruco.CharucoDetector(board).detectBoard(
            gray, markerCorners=marker_corners, markerIds=marker_ids
        )
    else:
        _, corners, ids = cv2.aruco.interpolateCornersCharuco(
            marker_corners, marker_ids, gray, board
        )
    if corners is None or ids is None or len(corners) < options.min_charuco_corners:
        return None
    points = corners.reshape(-1, 2).astype(np.float64)
    h, w = gray.shape[:2]
    hull = cv2.convexHull(points.astype(np.float32))
    coverage = float(cv2.contourArea(hull) / max(1, w * h))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    quality = min(1.0, coverage * 2.0) * min(1.0, sharpness / 150.0)
    return CharucoFrame(
        points, ids.reshape(-1).astype(np.int32), (w, h), marker_count, coverage, sharpness, quality
    )


def _object_points(board_config: CharucoBoardConfig, ids: np.ndarray) -> np.ndarray:
    # ChArUco IDs enumerate chessboard inner corners row-major.
    return (
        np.array(
            [
                (
                    int(i) % (board_config.squares_x - 1) + 1,
                    int(i) // (board_config.squares_x - 1) + 1,
                    0.0,
                )
                for i in ids
            ],
            dtype=np.float32,
        )
        * board_config.square_length_m
    )


def _diversity(frames: list[CharucoFrame]) -> float:
    if not frames:
        return 0.0
    centers = np.array([np.mean(f.image_points, axis=0) / f.image_size for f in frames])
    bins = {(min(3, int(x * 4)), min(3, int(y * 4))) for x, y in centers}
    return min(1.0, len(bins) / 8.0)


def calibrate(
    frames: list[CharucoFrame], board_config: CharucoBoardConfig, options: CalibrationOptions
) -> tuple[dict[str, Any] | None, CalibrationReport]:
    cv2 = _aruco()
    board_config.validate()
    options.validate()
    if not frames:
        return None, CalibrationReport(False, "no usable ChArUco frames", 0, 0.0, 0.0, None)
    frames = sorted(frames, key=lambda f: f.quality, reverse=True)[: options.max_frames]
    coverage = float(max(f.coverage for f in frames))
    diversity = _diversity(frames)
    if len(frames) < options.min_frames:
        return None, CalibrationReport(
            False, f"need {options.min_frames} frames", len(frames), coverage, diversity, None
        )
    if coverage < options.min_coverage or diversity < options.min_diversity:
        return None, CalibrationReport(
            False,
            "increase board coverage and pose diversity",
            len(frames),
            coverage,
            diversity,
            None,
        )

    def solve(active: list[CharucoFrame]):
        all_points = [f.image_points.reshape(-1, 1, 2).astype(np.float32) for f in active]
        all_ids = [f.ids.reshape(-1, 1).astype(np.int32) for f in active]
        obj = [_object_points(board_config, ids.reshape(-1)).reshape(-1, 1, 3) for ids in all_ids]
        flags = cv2.CALIB_RATIONAL_MODEL if options.model == "rational" else 0
        return cv2.calibrateCamera(obj, all_points, active[0].image_size, None, None, flags=flags)

    rms, matrix, distortion, rvecs, tvecs = solve(frames)
    errors = []
    for frame, obj, rvec, tvec in zip(
        frames, [_object_points(board_config, f.ids) for f in frames], rvecs, tvecs
    ):
        projected, _ = cv2.projectPoints(obj, rvec, tvec, matrix, distortion)
        errors.append(
            float(
                np.sqrt(
                    np.mean(np.sum((projected.reshape(-1, 2) - frame.image_points) ** 2, axis=1))
                )
            )
        )
    median = float(np.median(errors))
    mad = float(np.median(np.abs(np.asarray(errors) - median)))
    cutoff = median + max(options.outlier_mad_scale * mad, 0.5)
    active = [frame for frame, error in zip(frames, errors) if error <= cutoff]
    rejected = len(frames) - len(active)
    if len(active) >= options.min_frames and rejected:
        rms, matrix, distortion, _, _ = solve(active)
        frames = active
    if float(rms) > options.max_rms_px:
        return None, CalibrationReport(
            False,
            f"reprojection error {float(rms):.2f}px exceeds limit",
            len(frames),
            coverage,
            diversity,
            float(rms),
            rejected,
        )
    result = {
        "schema_version": 2,
        "method": "charuco",
        "board": asdict(board_config),
        "model": options.model,
        "width": frames[0].image_size[0],
        "height": frames[0].image_size[1],
        "camera_matrix": matrix.tolist(),
        "distortion_coefficients": distortion.reshape(-1).tolist(),
        "frames_used": len(frames),
        "coverage": coverage,
        "diversity": diversity,
        "reprojection_error_px": float(rms),
        "rms_reprojection_error_px": float(rms),
        "provisional": False,
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
    }
    return result, CalibrationReport(
        True, "calibration passed", len(frames), coverage, diversity, float(rms), rejected
    )


def write_calibration(path: str | Path, result: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=destination.name + ".", dir=destination.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
