from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .config import Calibration, ConfigError, file_revision
from .models import Detection, PoseCandidate, PoseMethod, PoseSolution
from .uncertainty import distortion_factors

# OpenCV's camera basis is +X right, +Y down, +Z forward.  WPILib's camera
# pose convention is NWU: +X forward, +Y left, +Z up.  This matrix converts a
# vector expressed in the OpenCV camera basis into the WPILib camera basis.
NWU_FROM_OPENCV = np.array([
    [0.0, 0.0, 1.0],
    [-1.0, 0.0, 0.0],
    [0.0, -1.0, 0.0],
], dtype=np.float64)

# OpenCV's IPPE tag plane is +X right, +Y down, +Z into the tag.  A WPILib
# field-layout tag uses +X out of the tag, +Y to the viewer's right, and +Z up.
# This is a proper rigid rotation (unlike merely projecting XY onto the YZ
# plane), so it can safely participate in pose composition.
TAG_NWU_FROM_OPENCV = np.array([
    [0.0, 0.0, -1.0],
    [1.0, 0.0, 0.0],
    [0.0, -1.0, 0.0],
], dtype=np.float64)


@dataclass(frozen=True)
class FieldTag:
    id: int
    field_from_tag: np.ndarray


@dataclass(frozen=True)
class FieldLayout:
    tags: dict[int, FieldTag]
    revision: int

    @classmethod
    def load(cls, path: str | Path, revision: int = 0) -> FieldLayout:
        source = Path(path)
        try:
            raw = json.loads(source.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot load field layout {source}: {exc}") from exc
        tag_items = raw.get("tags") if isinstance(raw, dict) else None
        if not isinstance(tag_items, list):
            raise ConfigError("field layout requires a tags array")
        tags: dict[int, FieldTag] = {}
        for item in tag_items:
            tag_id = int(item.get("ID", item.get("id")))
            pose = item["pose"]
            translation = pose["translation"]
            rotation = pose["rotation"]
            quaternion = rotation.get("quaternion", rotation)
            w = float(quaternion.get("W", quaternion.get("w")))
            x = float(quaternion.get("X", quaternion.get("x")))
            y = float(quaternion.get("Y", quaternion.get("y")))
            z = float(quaternion.get("Z", quaternion.get("z")))
            transform = np.eye(4, dtype=np.float64)
            transform[:3, :3] = quaternion_to_matrix(np.array([w, x, y, z]))
            transform[:3, 3] = [float(translation[axis]) for axis in ("x", "y", "z")]
            if tag_id in tags:
                raise ConfigError(f"duplicate field tag ID {tag_id}")
            tags[tag_id] = FieldTag(tag_id, transform)
        return cls(tags=tags, revision=revision or file_revision(source))


def quaternion_to_matrix(quaternion_wxyz: np.ndarray) -> np.ndarray:
    w, x, y, z = np.asarray(quaternion_wxyz, dtype=np.float64)
    norm = np.linalg.norm([w, x, y, z])
    if norm == 0:
        raise ConfigError("zero-length quaternion")
    w, x, y, z = np.array([w, x, y, z]) / norm
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def matrix_to_quaternion(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float64)
    trace = float(np.trace(matrix))
    if trace > 0:
        scale = np.sqrt(trace + 1.0) * 2
        values = [0.25 * scale, (matrix[2, 1] - matrix[1, 2]) / scale,
                  (matrix[0, 2] - matrix[2, 0]) / scale,
                  (matrix[1, 0] - matrix[0, 1]) / scale]
    elif matrix[0, 0] > matrix[1, 1] and matrix[0, 0] > matrix[2, 2]:
        scale = np.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2
        values = [(matrix[2, 1] - matrix[1, 2]) / scale, 0.25 * scale,
                  (matrix[0, 1] + matrix[1, 0]) / scale,
                  (matrix[0, 2] + matrix[2, 0]) / scale]
    elif matrix[1, 1] > matrix[2, 2]:
        scale = np.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2
        values = [(matrix[0, 2] - matrix[2, 0]) / scale,
                  (matrix[0, 1] + matrix[1, 0]) / scale, 0.25 * scale,
                  (matrix[1, 2] + matrix[2, 1]) / scale]
    else:
        scale = np.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2
        values = [(matrix[1, 0] - matrix[0, 1]) / scale,
                  (matrix[0, 2] + matrix[2, 0]) / scale,
                  (matrix[1, 2] + matrix[2, 1]) / scale, 0.25 * scale]
    result = np.asarray(values, dtype=np.float64)
    result /= np.linalg.norm(result)
    if result[0] < 0:
        result *= -1
    return result


def _transform(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = rotation
    result[:3, 3] = np.asarray(translation).reshape(3)
    return result


def _tag_corners(tag_size_m: float) -> np.ndarray:
    half = tag_size_m / 2.0
    # OpenCV IPPE_SQUARE's required canonical order.
    return np.array([
        [-half, half, 0.0], [half, half, 0.0],
        [half, -half, 0.0], [-half, -half, 0.0],
    ], dtype=np.float64)


def _tag_plane_to_field(field_from_tag: np.ndarray, local_corners: np.ndarray) -> np.ndarray:
    """Map canonical planar (u,v) corners into a WPILib tag's Y-Z plane."""
    homogeneous = np.column_stack((local_corners, np.ones(len(local_corners))))
    tag_from_plane = _transform(TAG_NWU_FROM_OPENCV, np.zeros(3))
    return (field_from_tag @ tag_from_plane @ homogeneous.T).T[:, :3]


def _rpy_matrix(rpy_deg: tuple[float, float, float]) -> np.ndarray:
    """Return Rz(yaw) @ Ry(pitch) @ Rx(roll) for right-handed NWU axes."""
    roll, pitch, yaw = np.deg2rad(np.asarray(rpy_deg, dtype=np.float64))
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float64)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float64)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=np.float64)
    return rz @ ry @ rx


def robot_from_camera_transform(
        translation_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
        rotation_rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> np.ndarray:
    """Build the configured camera-to-robot transform in WPILib/NWU space."""
    return _transform(_rpy_matrix(rotation_rpy_deg), np.asarray(translation_m))


class PoseSolver:
    def __init__(self, calibration: Calibration | None, layout: FieldLayout | None,
                 tag_size_m: float, *, tag_sizes: dict[int, float] | None = None) -> None:
        self.calibration = calibration
        self.layout = layout
        self.tag_size_m = tag_size_m
        self.local_corners = _tag_corners(tag_size_m)
        self.tag_sizes = tag_sizes or {}
        self.camera_matrix = (None if calibration is None else
                              np.asarray(calibration.camera_matrix, dtype=np.float64))
        self.distortion = (None if calibration is None else
                           np.asarray(calibration.distortion, dtype=np.float64))

    def solve(self, detections: tuple[Detection, ...]) -> PoseSolution:
        started = time.perf_counter_ns()
        if self.calibration is None:
            return self._empty(detections, "NO_CALIBRATION", started)
        if self.layout is None:
            return self._empty(detections, "NO_FIELD_LAYOUT", started)
        known = [detection for detection in detections if detection.id in self.layout.tags]
        reasons = {detection.id: "UNKNOWN_TAG_ID" for detection in detections
                   if detection.id not in self.layout.tags}
        if not known:
            return PoseSolution(rejection_reasons=reasons,
                                solve_ms=(time.perf_counter_ns() - started) / 1e6)
        try:
            if len(known) == 1:
                candidates = self._solve_single(known[0])
            else:
                candidates = self._solve_multi(known)
            factors = (np.asarray([d.distortion_factor_px for d in known], dtype=np.float64)
                       if all(d.distortion_factor_px is not None for d in known) else
                       distortion_factors(np.asarray([d.corners for d in known]), self.calibration))
            by_id = {d.id: float(factor) for d, factor in zip(known, factors)}
            candidates = tuple(replace(
                candidate,
                average_tag_distance_m=float(np.mean([
                    np.linalg.norm(self.layout.tags[tag_id].field_from_tag[:3, 3] -
                                   candidate.translation) for tag_id in candidate.tag_ids])),
                distortion_factor_px=float(np.mean([by_id[tag_id] for tag_id in candidate.tag_ids])),
            ) for candidate in candidates)
        except Exception as exc:  # noqa: BLE001 - OpenCV exposes backend-specific exceptions
            for detection in known:
                reasons[detection.id] = f"POSE_SOLVE_FAILED:{type(exc).__name__}"
            candidates = ()
        diagnostics = {}
        if candidates:
            import cv2

            best = min(candidates, key=lambda c: c.reprojection_error_px)
            field_from_camera = _transform(quaternion_to_matrix(best.quaternion_wxyz), best.translation)
            camera_cv_from_field = np.linalg.inv(field_from_camera @ _transform(NWU_FROM_OPENCV, np.zeros(3)))
            rvec = cv2.Rodrigues(camera_cv_from_field[:3, :3])[0]
            for detection in known:
                field_tag = self.layout.tags[detection.id].field_from_tag
                corners = _tag_plane_to_field(field_tag, _tag_corners(self.tag_sizes.get(detection.id, self.tag_size_m)))
                diagnostics[detection.id] = {
                    "distance_m": float(np.linalg.norm(field_tag[:3, 3] - best.translation)),
                    "error_px": self._reprojection_error(corners, detection.corners, rvec, camera_cv_from_field[:3, 3]),
                }
        used = frozenset(detection.id for detection in known) if candidates else frozenset()
        return PoseSolution(candidates=candidates, used_tag_ids=used, tag_diagnostics=diagnostics,
                            rejection_reasons=reasons,
                            solve_ms=(time.perf_counter_ns() - started) / 1e6)

    def _empty(self, detections: tuple[Detection, ...], reason: str, started: int) -> PoseSolution:
        return PoseSolution(rejection_reasons={detection.id: reason for detection in detections},
                            solve_ms=(time.perf_counter_ns() - started) / 1e6)

    def _solve_single(self, detection: Detection) -> tuple[PoseCandidate, ...]:
        import cv2

        local_corners = _tag_corners(self.tag_sizes.get(detection.id, self.tag_size_m))
        result = cv2.solvePnPGeneric(
            local_corners, detection.corners, self.camera_matrix, self.distortion,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if not result[0]:
            return ()
        field_from_tag = self.layout.tags[detection.id].field_from_tag
        tag_from_plane = _transform(TAG_NWU_FROM_OPENCV, np.zeros(3))
        candidates: list[PoseCandidate] = []
        for rvec, tvec in zip(result[1], result[2]):
            camera_from_plane = _transform(cv2.Rodrigues(rvec)[0], tvec)
            field_from_camera_cv = field_from_tag @ tag_from_plane @ np.linalg.inv(camera_from_plane)
            field_from_camera = field_from_camera_cv @ np.linalg.inv(
                _transform(NWU_FROM_OPENCV, np.zeros(3)))
            error = self._reprojection_error(local_corners, detection.corners, rvec, tvec)
            candidates.append(PoseCandidate(
                method=PoseMethod.SINGLE_TAG_IPPE_SQUARE,
                translation=field_from_camera[:3, 3].copy(),
                quaternion_wxyz=matrix_to_quaternion(field_from_camera[:3, :3]),
                reprojection_error_px=error,
                tag_ids=(detection.id,),
            ))
        return tuple(candidates)

    def _solve_multi(self, detections: list[Detection]) -> tuple[PoseCandidate, ...]:
        import cv2

        object_points: list[np.ndarray] = []
        image_points: list[np.ndarray] = []
        for detection in detections:
            field_from_tag = self.layout.tags[detection.id].field_from_tag
            field_corners = _tag_plane_to_field(field_from_tag, _tag_corners(self.tag_sizes.get(detection.id, self.tag_size_m)))
            object_points.append(field_corners)
            image_points.append(detection.corners)
        objects = np.concatenate(object_points).astype(np.float64)
        images = np.concatenate(image_points).astype(np.float64)
        result = cv2.solvePnPGeneric(objects, images, self.camera_matrix, self.distortion,
                                     flags=cv2.SOLVEPNP_SQPNP)
        if not result[0] or not result[1]:
            return ()
        rvec = np.asarray(result[1][0], dtype=np.float64)
        tvec = np.asarray(result[2][0], dtype=np.float64)
        refined, rvec, tvec = cv2.solvePnP(
            objects, images, self.camera_matrix, self.distortion, rvec, tvec,
            useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not refined:
            return ()
        camera_from_field = _transform(cv2.Rodrigues(rvec)[0], tvec)
        field_from_camera_cv = np.linalg.inv(camera_from_field)
        field_from_camera = field_from_camera_cv @ np.linalg.inv(
            _transform(NWU_FROM_OPENCV, np.zeros(3)))
        error = self._reprojection_error(objects, images, rvec, tvec)
        return (PoseCandidate(
            method=PoseMethod.MULTI_TAG_SQPNP,
            translation=field_from_camera[:3, 3].copy(),
            quaternion_wxyz=matrix_to_quaternion(field_from_camera[:3, :3]),
            reprojection_error_px=error,
            tag_ids=tuple(detection.id for detection in detections),
        ),)

    def _reprojection_error(self, objects: np.ndarray, images: np.ndarray,
                            rvec: np.ndarray, tvec: np.ndarray) -> float:
        import cv2

        projected = cv2.projectPoints(objects, rvec, tvec, self.camera_matrix,
                                      self.distortion)[0].reshape(-1, 2)
        residuals = projected - np.asarray(images).reshape(-1, 2)
        return float(np.sqrt(np.mean(np.sum(residuals * residuals, axis=1))))


def select_robot_pose(solution: PoseSolution,
                      robot_from_camera: np.ndarray) -> PoseCandidate | None:
    """Select one camera candidate and express the corresponding robot pose."""
    selected = min(
        enumerate(solution.candidates),
        key=lambda pair: (pair[1].reprojection_error_px, pair[0]),
        default=None,
    )
    if selected is None:
        return None
    candidate = selected[1]
    robot_from_camera = np.asarray(robot_from_camera, dtype=np.float64)
    if robot_from_camera.shape != (4, 4):
        raise ConfigError("robot_from_camera must be a 4x4 transform")
    field_from_camera = _transform(
        quaternion_to_matrix(candidate.quaternion_wxyz), candidate.translation)
    field_from_robot = field_from_camera @ np.linalg.inv(robot_from_camera)
    return PoseCandidate(
        method=candidate.method,
        translation=field_from_robot[:3, 3].copy(),
        quaternion_wxyz=matrix_to_quaternion(field_from_robot[:3, :3]),
        reprojection_error_px=candidate.reprojection_error_px,
        tag_ids=candidate.tag_ids,
        average_tag_distance_m=candidate.average_tag_distance_m,
        distortion_factor_px=candidate.distortion_factor_px,
    )
