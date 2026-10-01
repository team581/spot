"""Hardware-independent calibration session state and capture policy."""
from __future__ import annotations

import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .charuco import (CalibrationOptions, CalibrationReport, CharucoBoardConfig,
                      CharucoFrame, calibrate, detect_frame, make_board, write_calibration, _diversity)


def frame_motion(current: CharucoFrame, previous: CharucoFrame) -> float:
    """RMS movement of matching board corners, as a fraction of image diagonal.

    Comparing IDs avoids mistaking newly visible corners for board movement.
    Disjoint board regions are useful new views even without shared corners.
    """
    if current.image_size != previous.image_size:
        return float("inf")
    _, current_indices, previous_indices = np.intersect1d(
        current.ids, previous.ids, return_indices=True)
    if len(current_indices) < 4:
        return float("inf")
    displacement = current.image_points[current_indices] - previous.image_points[previous_indices]
    return float(np.sqrt(np.mean(np.sum(displacement ** 2, axis=1))) /
                 np.linalg.norm(current.image_size))


def _view_signature(sample: CharucoFrame, board: CharucoBoardConfig) -> np.ndarray | None:
    """Uncalibrated shape/scale proxy, independent of translation and visible IDs.

    Fit the board plane using known corner IDs, then measure its Jacobian at
    the fixed board center. Cropping the board must not masquerade as a new
    distance. These are capture guidance heuristics, not calibrated pose or
    an estimate of intrinsic-parameter uncertainty.
    """
    import cv2
    ids = sample.ids.reshape(-1)
    points = np.column_stack((ids % (board.squares_x - 1) + 1,
                              ids // (board.squares_x - 1) + 1)).astype(float)
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
    return np.array([np.log(np.sqrt(area)), np.log(lengths[0] / lengths[1]),
                     np.dot(a, b) / np.prod(lengths),
                     *(h[2, :2] / projected[2] * max(board.squares_x, board.squares_y))])


def coverage_state(samples: list[CharucoFrame], board: CharucoBoardConfig,
                   size: int = 12) -> dict:
    """Score local evidence, requiring six distinct views, scale AND tilt spread.

    Similar views are merged using continuous distances (no bin-boundary
    credit). Translation, roll alone, and duplicate captures cannot make a
    region green. Only regions containing measured corners receive evidence.
    """
    views = [[[] for _ in range(size)] for _ in range(size)]
    particles = {}
    thresholds = np.array([np.log(1.15), .12, .12, .12, .12])
    for sample in samples:
        normalized = sample.image_points / sample.image_size
        valid = normalized[np.isfinite(normalized).all(axis=1) &
                           (normalized >= 0).all(axis=1) & (normalized < 1).all(axis=1)]
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
                scores[row, col] = min(len(evidence) / 6, spread[0] / np.log(1.3),
                                       max(spread[1:]) / .25, 1.0)
    return {"coverage_grid": scores.tolist(),
            "coverage_progress": float(scores.mean()),
            "coverage_good_fraction": float(np.mean(scores >= 1)),
            "coverage_particles": [{"x": x, "y": y, "progress": float(scores[region])}
                                   for x, y, region in particles.values()]}


@dataclass
class CameraSession:
    camera_id: str
    source: Callable[[], np.ndarray] | None = None
    running: bool = False
    mode: str = "manual"
    last_frame: np.ndarray | None = None
    last_detection: CharucoFrame | None = None
    samples: list[CharucoFrame] = field(default_factory=list)
    report: CalibrationReport | None = None
    error: str | None = None
    capture_reason: str = "Show the board"
    calibrating: bool = False
    motion: float = 0.0
    coverage_cache: dict = field(default_factory=dict)
    coverage_cache_key: tuple | None = None

    def coverage(self, board: CharucoBoardConfig) -> dict:
        key = (len(self.samples), board)
        if key != self.coverage_cache_key:
            self.coverage_cache = coverage_state(self.samples, board)
            self.coverage_cache_key = key
        return self.coverage_cache

    def tick(self, board: CharucoBoardConfig, options: CalibrationOptions) -> CharucoFrame | None:
        if not self.running or self.source is None:
            return self.last_detection
        self.last_frame = self.source()
        self.last_detection = detect_frame(self.last_frame, board, options)
        if self.mode == "auto" and self.last_detection is not None:
            self.accept(options, automatic=True, board=board)
        elif self.last_detection is None:
            self.capture_reason = "Show more sharp board corners"
        return self.last_detection

    def accept(self, options: CalibrationOptions, automatic: bool = False,
               board: CharucoBoardConfig | None = None) -> bool:
        if self.calibrating:
            return False
        if self.last_detection is None:
            self.capture_reason = "No usable board detected"
            return False
        if automatic and board is not None:
            grid = np.asarray(self.coverage(board)["coverage_grid"])
            points = self.last_detection.image_points / self.last_detection.image_size
            points = points[np.isfinite(points).all(axis=1) &
                            (points >= 0).all(axis=1) & (points < 1).all(axis=1)]
            if len(points):
                cells = (points * grid.shape[0]).astype(int)
                if np.mean(grid[cells[:, 1], cells[:, 0]] >= 1) > .90:
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
        self.report = None
        self.capture_reason = "Captured new view"
        return True


class CalibrationSession:
    def __init__(self, cameras: list[str], root: str | Path, sources: dict[str, Callable[[], np.ndarray]] | None = None):
        self.id = secrets.token_urlsafe(12)
        self.root = Path(root) / self.id
        self.root.mkdir(parents=True, exist_ok=True)
        self.cameras = {camera_id: CameraSession(camera_id, (sources or {}).get(camera_id)) for camera_id in cameras}
        self.board = CharucoBoardConfig()
        self.options = CalibrationOptions()
        self.created = time.monotonic()
        self._lock = threading.RLock()

    def configure(self, board: CharucoBoardConfig, options: CalibrationOptions) -> None:
        board.validate(); options.validate()
        make_board(board)  # Fail before starting capture for undersized dictionaries.
        self.board, self.options = board, options

    def start(self, camera_id: str | None = None, mode: str = "manual") -> None:
        if mode not in {"manual", "auto"}:
            raise ValueError("mode must be manual or auto")
        with self._lock:
            for camera in self.cameras.values():
                if camera_id is None or camera.camera_id == camera_id:
                    if camera.calibrating:
                        raise RuntimeError("camera is calibrating")
                    camera.mode, camera.running, camera.error = mode, True, None

    def stop(self, camera_id: str | None = None) -> None:
        with self._lock:
            for camera in self.cameras.values():
                if camera_id is None or camera.camera_id == camera_id:
                    camera.running = False

    def capture(self, camera_id: str) -> bool:
        with self._lock:
            return self.cameras[camera_id].accept(self.options)

    def tick(self, camera_id: str) -> CharucoFrame | None:
        with self._lock:
            camera = self.cameras[camera_id]
            if not camera.running or camera.source is None:
                return camera.last_detection
            board, options = self.board, self.options
        # Detection runs independently of preview requests and status polling.
        frame = camera.source()
        detection = detect_frame(frame, board, options)
        with self._lock:
            if self.cameras[camera_id] is not camera or not camera.running:
                return None
            camera.last_frame, camera.last_detection, camera.error = frame, detection, None
            if camera.mode == "auto" and detection is not None:
                camera.accept(options, automatic=True, board=board)
            elif detection is None:
                camera.capture_reason = "Show more sharp board corners"
            return detection

    def restart(self, camera_id: str) -> None:
        with self._lock:
            old = self.cameras[camera_id]
            self.cameras[camera_id] = CameraSession(camera_id, old.source, running=True, mode=old.mode)

    def ready(self, camera_id: str) -> bool:
        with self._lock:
            camera = self.cameras[camera_id]
            return (camera.running and camera.mode == "auto" and not camera.calibrating
                    and camera.report is None and len(camera.samples) >= self.options.min_frames
                    and max(f.coverage for f in camera.samples) >= self.options.min_coverage
                    and _diversity(camera.samples) >= self.options.min_diversity
                    and (camera.coverage(self.board)["coverage_good_fraction"] >= .90
                         or len(camera.samples) >= self.options.max_frames))

    def compute(self, camera_id: str) -> tuple[dict | None, CalibrationReport]:
        with self._lock:
            camera = self.cameras[camera_id]
            if camera.calibrating:
                raise RuntimeError("camera is already calibrating")
            camera.running = False
            camera.calibrating = True
            camera.error = None
            samples, board, options = list(camera.samples), self.board, self.options
        # OpenCV may take seconds: status and other cameras must remain responsive.
        try:
            result, report = calibrate(samples, board, options)
            with self._lock:
                camera.report = report
            return result, report
        except Exception as exc:
            with self._lock:
                camera.error = f"Calibration failed: {exc}"
            raise
        finally:
            with self._lock:
                camera.calibrating = False

    def save(self, results: dict[str, dict], paths: dict[str, str], override: bool = False) -> None:
        with self._lock:
            if not results:
                raise ValueError("no calibration results supplied")
            for camera_id, result in results.items():
                report = self.cameras[camera_id].report
                if report is None or (not report.accepted and not override):
                    raise ValueError(f"camera {camera_id} has not passed validation")
            for camera_id, result in results.items():
                result = dict(result); result["camera_id"] = camera_id
                write_calibration(paths[camera_id], result)

    def status(self) -> dict:
        with self._lock:
            return {camera_id: {"running": camera.running, "calibrating": camera.calibrating, "frames": len(camera.samples),
                                "detected": camera.last_detection is not None,
                                "coverage": 0 if camera.last_detection is None else camera.last_detection.coverage,
                                **camera.coverage(self.board),
                                "mode": camera.mode,
                                "capture_reason": camera.capture_reason,
                                "motion": camera.motion if np.isfinite(camera.motion) else None,
                                "report": None if camera.report is None else camera.report.__dict__,
                                "error": camera.error} for camera_id, camera in self.cameras.items()}

    def close(self) -> None:
        self.stop(); shutil.rmtree(self.root, ignore_errors=True)
