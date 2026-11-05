from __future__ import annotations

import json
from dataclasses import replace

import pytest

from spot_vision.config import Calibration, ConfigError, load_calibration, load_config


def valid_config(tmp_path):
    path = tmp_path / "spot.json"
    path.write_text(
        json.dumps(
            {
                "nt": {"enabled": False},
                "cameras": [
                    {
                        "id": "front",
                        "enabled": True,
                        "selector": {"device": "/dev/video-test"},
                        "format": "YUY2",
                        "width": 1280,
                        "height": 800,
                        "fps": 60,
                    }
                ],
            }
        )
    )
    return path


def test_load_config_defaults_and_relative_paths(tmp_path):
    path = valid_config(tmp_path)
    raw = json.loads(path.read_text())
    raw["field_layout"] = "field.json"
    raw["cameras"][0]["calibration"] = "front.json"
    path.write_text(json.dumps(raw))
    config = load_config(path)
    assert config.camera("front").width == 1280
    assert config.camera("front").calibration == (tmp_path / "front.json").resolve()
    assert config.field_layout == (tmp_path / "field.json").resolve()


def test_load_config_robot_extrinsics(tmp_path):
    path = valid_config(tmp_path)
    raw = json.loads(path.read_text())
    raw["cameras"][0]["robot_from_camera"] = {
        "translation_m": [0.0, 0.1, 0.0],
        "rotation_rpy_deg": [0.0, -20.0, 0.0],
    }
    path.write_text(json.dumps(raw))
    camera = load_config(path).camera("front")
    assert camera.robot_from_camera_translation == (0.0, 0.1, 0.0)
    assert camera.robot_from_camera_rpy_deg == (0.0, -20.0, 0.0)


def test_invalid_robot_extrinsics_are_rejected(tmp_path):
    path = valid_config(tmp_path)
    raw = json.loads(path.read_text())
    raw["cameras"][0]["robot_from_camera"] = {
        "translation_m": [0.0, float("nan"), 0.0],
        "rotation_rpy_deg": [0.0, -20.0, 0.0],
    }
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="translation_m"):
        load_config(path)


def test_duplicate_camera_rejected(tmp_path):
    path = valid_config(tmp_path)
    raw = json.loads(path.read_text())
    raw["cameras"].append(raw["cameras"][0])
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="duplicate camera"):
        load_config(path)


def test_cuda_dimensions_must_be_multiples_of_eight(tmp_path):
    path = valid_config(tmp_path)
    raw = json.loads(path.read_text())
    raw["cameras"][0]["width"] = 1279
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="multiples of 8"):
        load_config(path)


@pytest.mark.parametrize("rotation", [True, 90, 270, "180", -180])
def test_unsupported_image_rotation_is_rejected(tmp_path, rotation):
    path = valid_config(tmp_path)
    raw = json.loads(path.read_text())
    raw["cameras"][0]["image_rotation_deg"] = rotation
    path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="image_rotation_deg"):
        load_config(path)


def test_rotated_calibration_projects_to_rotated_pixels(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    path = valid_config(tmp_path)
    camera = replace(load_config(path).cameras[0], width=1280, height=720, image_rotation_deg=180)
    raw = Calibration(
        "1",
        1280,
        720,
        "MJPEG",
        ((1001.0, 0.0, 630.2), (0.0, 997.0, 355.7), (0.0, 0.0, 1.0)),
        (0.1, -0.04, 0.008, -0.006, 0.002),
    )
    rotated = raw.for_image_rotation(camera)
    points = np.array([[0.1, -0.2, 2.0], [-0.3, 0.15, 1.5], [0.05, 0.08, 3.0]], dtype=np.float64)
    pixels = cv2.projectPoints(
        points, np.zeros(3), np.zeros(3), np.asarray(raw.camera_matrix), np.asarray(raw.distortion)
    )[0]
    corrected = cv2.projectPoints(
        points * [-1, -1, 1],
        np.zeros(3),
        np.zeros(3),
        np.asarray(rotated.camera_matrix),
        np.asarray(rotated.distortion),
    )[0]
    assert np.allclose(corrected[:, 0, 0], camera.width - 1 - pixels[:, 0, 0])
    assert np.allclose(corrected[:, 0, 1], camera.height - 1 - pixels[:, 0, 1])
    assert raw.for_image_rotation(replace(camera, image_rotation_deg=0)) is raw


def test_calibration_identity_validation(tmp_path):
    path = valid_config(tmp_path)
    camera = load_config(path).camera("front")
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(
        json.dumps(
            {
                "camera_id": "front",
                "width": 1280,
                "height": 800,
                "pixel_format": "YUY2",
                "camera_matrix": [[900, 0, 640], [0, 900, 400], [0, 0, 1]],
                "distortion_coefficients": [0, 0, 0, 0, 0],
            }
        )
    )
    load_calibration(calibration_path).validate_for(camera)
    raw = json.loads(calibration_path.read_text())
    raw["width"] = 640
    calibration_path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="calibration mismatch"):
        load_calibration(calibration_path).validate_for(camera)
