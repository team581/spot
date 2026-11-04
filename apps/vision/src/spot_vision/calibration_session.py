"""Hardware-independent calibration session state and capture policy."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .charuco import (
    CalibrationOptions,
    CharucoBoardConfig,
    CharucoFrame,
)


def frame_motion(current: CharucoFrame, previous: CharucoFrame) -> float:
    """RMS movement of matching board corners, as a fraction of image diagonal.

    Comparing IDs avoids mistaking newly visible corners for board movement.
    Disjoint board regions are useful new views even without shared corners.
    """
    if current.image_size != previous.image_size:
        return float("inf")
    _, current_indices, previous_indices = np.intersect1d(
        current.ids, previous.ids, return_indices=True
    )
    if len(current_indices) < 4:
        return float("inf")
    displacement = current.image_points[current_indices] - previous.image_points[previous_indices]
    return float(
        np.sqrt(np.mean(np.sum(displacement**2, axis=1))) / np.linalg.norm(current.image_size)
    )


def _view_signature(sample: CharucoFrame, board: CharucoBoardConfig) -> np.ndarray | None:
    """Uncalibrated shape/scale proxy, independent of translation and visible IDs.

    Fit the board plane using known corner IDs, then measure its Jacobian at
    the fixed board center. Cropping the board must not masquerade as a new
    distance. These are capture guidance heuristics, not calibrated pose or
    an estimate of intrinsic-parameter uncertainty.
    """
    import cv2

    ids = sample.ids.reshape(-1)
    points = np.column_stack(
        (ids % (board.squares_x - 1) + 1, ids // (board.squares_x - 1) + 1)
    ).astype(float)
    if len(points) < 4 or np.linalg.matrix_rank(points - points.mean(axis=0)) < 2:
        return None
    # Isotropic image normalization preserves shape for nonsquare feeds.
    h, _ = cv2.findHomography(points, sample.image_points / max(sample.image_size), 0)
    if h is None or not np.isfinite(h).all():
        return None
    center = np.array([board.squares_x / 2, board.squares_y / 2, 1.0])
    projected = h @ center
    if abs(projected[2]) < 1e-8:
        return None
    jacobian = (h[:2, :2] - np.outer(projected[:2] / projected[2], h[2, :2])) / projected[2]
    a, b = jacobian[:, 0], jacobian[:, 1]
    lengths = np.linalg.norm(jacobian, axis=0)
    area = abs(np.linalg.det(jacobian))
    if min(lengths) < 1e-8 or area < 1e-10:
        return None
    return np.array(
        [
            np.log(np.sqrt(area)),
            np.log(lengths[0] / lengths[1]),
            np.dot(a, b) / np.prod(lengths),
            *(h[2, :2] / projected[2] * max(board.squares_x, board.squares_y)),
        ]
    )


def coverage_state(samples: list[CharucoFrame], board: CharucoBoardConfig, size: int = 12) -> dict:
    """Score local evidence, requiring six distinct views, scale AND tilt spread.

    Similar views are merged using continuous distances (no bin-boundary
    credit). Translation, roll alone, and duplicate captures cannot make a
    region green. Only regions containing measured corners receive evidence.
    """
    views = [[[] for _ in range(size)] for _ in range(size)]
    particles = {}
    thresholds = np.array([np.log(1.15), 0.12, 0.12, 0.12, 0.12])
    for sample in samples:
        normalized = sample.image_points / sample.image_size
        valid = normalized[
            np.isfinite(normalized).all(axis=1)
            & (normalized >= 0).all(axis=1)
            & (normalized < 1).all(axis=1)
        ]
        signature = _view_signature(sample, board)
        touched = set()
        for x, y in valid:
            region = (int(y * size), int(x * size))
            # Bound payload/density; retain an actual observed corner location.
            particles.setdefault((int(x * 96), int(y * 72)), (float(x), float(y), region))
            touched.add(region)
        if signature is None:
            continue
        for row, col in touched:
            previous = views[row][col]
            if all(np.max(np.abs(signature - old) / thresholds) >= 1 for old in previous):
                previous.append(signature)
    scores = np.zeros((size, size))
    for row in range(size):
        for col in range(size):
            evidence = views[row][col]
            if evidence:
                spread = np.ptp(evidence, axis=0)
                # 30% apparent scale range and substantial foreshortening or
                # perspective change, in addition to independent observations.
                scores[row, col] = min(
                    len(evidence) / 6, spread[0] / np.log(1.3), max(spread[1:]) / 0.25, 1.0
                )
    return {
        "coverage_grid": scores.tolist(),
        "coverage_progress": float(scores.mean()),
        "coverage_good_fraction": float(np.mean(scores >= 1)),
        "coverage_particles": [
            {"x": x, "y": y, "progress": float(scores[region])}
            for x, y, region in particles.values()
        ],
    }


@dataclass
class CameraSession:
    camera_id: str
    last_detection: CharucoFrame | None = None
    samples: list[CharucoFrame] = field(default_factory=list)
    capture_reason: str = "Show the board"
    motion: float = 0.0
    coverage_cache: dict = field(default_factory=dict)
    coverage_cache_key: tuple | None = None

    def coverage(self, board: CharucoBoardConfig) -> dict:
        key = (len(self.samples), board)
        if key != self.coverage_cache_key:
            self.coverage_cache = coverage_state(self.samples, board)
            self.coverage_cache_key = key
        return self.coverage_cache

    def accept(
        self,
        options: CalibrationOptions,
        automatic: bool = False,
        board: CharucoBoardConfig | None = None,
    ) -> bool:
        if self.last_detection is None:
            self.capture_reason = "No usable board detected"
            return False
        if automatic and board is not None:
            grid = np.asarray(self.coverage(board)["coverage_grid"])
            points = self.last_detection.image_points / self.last_detection.image_size
            points = points[
                np.isfinite(points).all(axis=1)
                & (points >= 0).all(axis=1)
                & (points < 1).all(axis=1)
            ]
            if len(points):
                cells = (points * grid.shape[0]).astype(int)
                if np.mean(grid[cells[:, 1], cells[:, 0]] >= 1) > 0.90:
                    self.capture_reason = "Already green — move to yellow or unseen regions"
                    return False
        if len(self.samples) >= options.max_frames:
            self.capture_reason = "Capture limit reached — calibrate or reset"
            return False
        if self.samples:
            self.motion = frame_motion(self.last_detection, self.samples[-1])
            if automatic and self.motion < options.min_frame_motion:
                self.capture_reason = "Move or tilt the board for the next view"
                return False
        self.samples.append(self.last_detection)
        self.capture_reason = "Captured new view"
        return True
