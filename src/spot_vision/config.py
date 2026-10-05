from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DetectorConfig:
    backend: str = "cuda"
    fallback_to_cpu: bool = True
    family: str = "tag36h11"
    decimate: float = 2.0
    blur: float = 0.0
    threads: int = 1
    refine_edges: bool = True
    max_hamming: int = 2


@dataclass(frozen=True)
class CameraSelector:
    serial: str | None = None
    by_id: str | None = None
    by_path: str | None = None
    device: str | None = None

    def configured(self) -> bool:
        return any((self.serial, self.by_id, self.by_path, self.device))


@dataclass(frozen=True)
class CameraConfig:
    id: str
    enabled: bool
    selector: CameraSelector
    format: str
    width: int
    height: int
    fps: int
    exposure_us: int | None
    gain: int | None
    auto_exposure: bool
    calibration: Path | None
    timestamp_correction_us: int
    config_revision: int
    detector: DetectorConfig
    image_rotation_deg: int = 0
    # Transform from the camera's WPILib/NWU frame to robot frame.  The
    # translation is the camera origin in robot coordinates and RPY uses
    # right-handed rotations (Rz(yaw) @ Ry(pitch) @ Rx(roll)).
    robot_from_camera_translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    robot_from_camera_rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    contrast: int | None = None
    sharpness: int | None = None


@dataclass(frozen=True)
class NtConfig:
    enabled: bool = True
    mode: str = "client"
    server: str | None = None
    team: int | None = None
    identity: str = "spot-vision"


@dataclass(frozen=True)
class ServiceConfig:
    schema_version: int
    field_layout: Path | None
    field_revision: int
    tag_size_m: float
    result_queue_capacity: int
    nt: NtConfig
    cameras: tuple[CameraConfig, ...]
    source_path: Path = field(compare=False)

    def camera(self, camera_id: str) -> CameraConfig:
        for camera in self.cameras:
            if camera.id == camera_id:
                return camera
        raise ConfigError(f"unknown camera {camera_id!r}")


@dataclass(frozen=True)
class Calibration:
    camera_id: str | None
    width: int
    height: int
    pixel_format: str
    camera_matrix: tuple[tuple[float, float, float], ...]
    distortion: tuple[float, ...]
    reprojection_error_px: float | None = None
    provisional: bool = False

    def validate_for(self, camera: CameraConfig) -> None:
        if len(self.distortion) not in {4, 5, 8, 12, 14}:
            raise ConfigError("calibration distortion requires 4, 5, 8, 12, or 14 coefficients")
        if not all(math.isfinite(value) for row in self.camera_matrix for value in row) or not all(
                math.isfinite(value) for value in self.distortion):
            raise ConfigError("calibration intrinsics must be finite")
        if self.camera_matrix[0][0] <= 0 or self.camera_matrix[1][1] <= 0:
            raise ConfigError("calibration focal lengths must be positive")
        mismatches: list[str] = []
        if self.camera_id and self.camera_id != camera.id:
            mismatches.append(f"camera_id={self.camera_id!r}")
        if (self.width, self.height) != (camera.width, camera.height):
            mismatches.append(f"resolution={self.width}x{self.height}")
        if self.pixel_format.upper() != camera.format.upper():
            mismatches.append(f"pixel_format={self.pixel_format!r}")
        if mismatches:
            raise ConfigError("calibration mismatch: " + ", ".join(mismatches))

    def for_image_rotation(self, camera: CameraConfig) -> Calibration:
        """Express raw-sensor intrinsics in the frame delivered to detection."""
        if camera.image_rotation_deg == 0:
            return self
        if camera.image_rotation_deg != 180:
            raise ConfigError("unsupported image rotation")
        if len(self.distortion) >= 14 and any(self.distortion[12:14]):
            raise ConfigError("180-degree rotation does not support tilted-sensor distortion")
        matrix = [list(row) for row in self.camera_matrix]
        matrix[0][2] = camera.width - 1 - matrix[0][2]
        matrix[1][2] = camera.height - 1 - matrix[1][2]
        distortion = list(self.distortion)
        # OpenCV tangential and thin-prism terms are even under (x, y) ->
        # (-x, -y), so their coefficients change sign in the rotated frame.
        for index in (2, 3, 8, 9, 10, 11):
            if index < len(distortion):
                distortion[index] = -distortion[index]
        return replace(self, camera_matrix=tuple(tuple(row) for row in matrix),
                       distortion=tuple(distortion))


def _required(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"missing {where}.{key}")
    return mapping[key]


def _path(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: str | Path) -> ServiceConfig:
    source = Path(path).resolve()
    try:
        raw = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be an object")

    camera_items = _required(raw, "cameras", "config")
    if not isinstance(camera_items, list) or not camera_items:
        raise ConfigError("config.cameras must be a non-empty array")

    cameras: list[CameraConfig] = []
    ids: set[str] = set()
    for index, item in enumerate(camera_items):
        where = f"cameras[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{where} must be an object")
        camera_id = str(_required(item, "id", where))
        if camera_id in ids:
            raise ConfigError(f"duplicate camera id {camera_id!r}")
        ids.add(camera_id)
        selector_raw = item.get("selector", {})
        selector = CameraSelector(**{key: selector_raw.get(key) for key in
                                    ("serial", "by_id", "by_path", "device")})
        enabled = bool(item.get("enabled", True))
        if enabled and not selector.configured():
            raise ConfigError(f"{where}.selector has no usable identity")
        detector_raw = item.get("detector", {})
        detector = DetectorConfig(**detector_raw)
        if detector.backend not in {"cuda", "cpu"}:
            raise ConfigError(f"{where}.detector.backend must be cuda or cpu")
        width = int(_required(item, "width", where))
        height = int(_required(item, "height", where))
        fps = int(_required(item, "fps", where))
        if min(width, height, fps) <= 0:
            raise ConfigError(f"{where} dimensions and fps must be positive")
        if detector.backend == "cuda" and (width % 8 or height % 8):
            raise ConfigError(f"{where} CUDA dimensions must be multiples of 8")
        if width % 2:
            raise ConfigError(f"{where}.width must be even for packed YUYV frames")
        rotation = item.get("image_rotation_deg", 0)
        if type(rotation) is not int or rotation not in (0, 180):
            raise ConfigError(f"{where}.image_rotation_deg must be 0 or 180")
        extrinsics = item.get("robot_from_camera", {})
        if not isinstance(extrinsics, dict):
            raise ConfigError(f"{where}.robot_from_camera must be an object")
        translation = extrinsics.get("translation_m", (0.0, 0.0, 0.0))
        rpy = extrinsics.get("rotation_rpy_deg", (0.0, 0.0, 0.0))
        if (not isinstance(translation, (list, tuple)) or len(translation) != 3 or
                not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) for value in translation)):
            raise ConfigError(f"{where}.robot_from_camera.translation_m must have 3 numbers")
        if (not isinstance(rpy, (list, tuple)) or len(rpy) != 3 or
                not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) for value in rpy)):
            raise ConfigError(f"{where}.robot_from_camera.rotation_rpy_deg must have 3 numbers")
        cameras.append(CameraConfig(
            id=camera_id,
            enabled=enabled,
            selector=selector,
            format=str(item.get("format", "YUY2")).upper(),
            width=width,
            height=height,
            fps=fps,
            exposure_us=(None if item.get("exposure_us") is None else int(item["exposure_us"])),
            gain=(None if item.get("gain") is None else int(item["gain"])),
            auto_exposure=bool(item.get("auto_exposure", False)),
            calibration=_path(source.parent, item.get("calibration")),
            timestamp_correction_us=int(item.get("timestamp_correction_us", 0)),
            config_revision=int(item.get("config_revision", 1)),
            detector=detector,
            image_rotation_deg=rotation,
            robot_from_camera_translation=tuple(float(value) for value in translation),
            robot_from_camera_rpy_deg=tuple(float(value) for value in rpy),
            contrast=_image_control(item, "contrast", where),
            sharpness=_image_control(item, "sharpness", where),
        ))

    nt_raw = raw.get("nt", {})
    nt = NtConfig(**nt_raw)
    if nt.mode not in {"client", "server"}:
        raise ConfigError("nt.mode must be client or server")
    if nt.enabled and nt.mode == "client" and nt.server is None and nt.team is None:
        raise ConfigError("NT client requires nt.server or nt.team")

    capacity = int(raw.get("result_queue_capacity", 32))
    if capacity < 1:
        raise ConfigError("result_queue_capacity must be positive")
    return ServiceConfig(
        schema_version=int(raw.get("schema_version", 1)),
        field_layout=_path(source.parent, raw.get("field_layout")),
        field_revision=int(raw.get("field_revision", 0)),
        tag_size_m=float(raw.get("tag_size_m", 0.1651)),
        result_queue_capacity=capacity,
        nt=nt,
        cameras=tuple(cameras),
        source_path=source,
    )


def _image_control(item: dict, name: str, where: str) -> int | None:
    value = item.get(name)
    if value is not None and (type(value) is not int or not 0 <= value <= 100):
        raise ConfigError(f"{where}.{name} must be an integer between 0 and 100")
    return value


def load_calibration(path: str | Path) -> Calibration:
    source = Path(path)
    try:
        raw = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot load calibration {source}: {exc}") from exc
    matrix = raw.get("camera_matrix", raw.get("cameraMatrix"))
    distortion = raw.get("distortion_coefficients", raw.get("distCoeffs"))
    if isinstance(matrix, dict):
        matrix = matrix.get("data")
    if isinstance(distortion, dict):
        distortion = distortion.get("data")
    if isinstance(matrix, list) and len(matrix) == 9 and not isinstance(matrix[0], list):
        matrix = [matrix[0:3], matrix[3:6], matrix[6:9]]
    if not (isinstance(matrix, list) and len(matrix) == 3 and
            all(isinstance(row, list) and len(row) == 3 for row in matrix)):
        raise ConfigError("calibration camera_matrix must be 3x3")
    if not isinstance(distortion, list) or len(distortion) < 4:
        raise ConfigError("calibration distortion_coefficients must have at least four values")
    resolution = raw.get("resolution", {})
    width = int(raw.get("width", resolution.get("width", 0)))
    height = int(raw.get("height", resolution.get("height", 0)))
    if width <= 0 or height <= 0:
        raise ConfigError("calibration requires positive width and height")
    return Calibration(
        camera_id=raw.get("camera_id"),
        width=width,
        height=height,
        pixel_format=str(raw.get("pixel_format", "YUY2")),
        camera_matrix=tuple(tuple(float(value) for value in row) for row in matrix),
        distortion=tuple(float(value) for value in distortion),
        reprojection_error_px=(None if raw.get("reprojection_error_px") is None
                               else float(raw["reprojection_error_px"])),
        provisional=bool(raw.get("provisional", False)),
    )


def file_revision(path: Path) -> int:
    digest = hashlib.sha256(path.read_bytes()).digest()
    # Protobuf carries this as uint64, but NetworkTables integer topics are
    # signed int64. Keep automatic revisions non-negative and portable across
    # both transports while retaining 63 bits of the content hash.
    return int.from_bytes(digest[:8], "big", signed=False) & ((1 << 63) - 1)
