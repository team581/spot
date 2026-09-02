from __future__ import annotations

import json

import pytest

from buddy_vision.config import ConfigError, load_calibration, load_config


def valid_config(tmp_path):
    path = tmp_path / "buddy.json"
    path.write_text(json.dumps({
        "nt": {"enabled": False},
        "cameras": [{
            "id": "front", "enabled": True,
            "selector": {"device": "/dev/video-test"},
            "format": "YUY2", "width": 1280, "height": 800, "fps": 60,
        }],
    }))
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
    assert config.result_queue_capacity == 32


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


def test_calibration_identity_validation(tmp_path):
    path = valid_config(tmp_path)
    camera = load_config(path).camera("front")
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(json.dumps({
        "camera_id": "front", "width": 1280, "height": 800, "pixel_format": "YUY2",
        "camera_matrix": [[900, 0, 640], [0, 900, 400], [0, 0, 1]],
        "distortion_coefficients": [0, 0, 0, 0, 0],
    }))
    load_calibration(calibration_path).validate_for(camera)
    raw = json.loads(calibration_path.read_text())
    raw["width"] = 640
    calibration_path.write_text(json.dumps(raw))
    with pytest.raises(ConfigError, match="calibration mismatch"):
        load_calibration(calibration_path).validate_for(camera)
