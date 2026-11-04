"""Calibration oracle: independently project known optics across board poses."""

from dataclasses import replace

import cv2
import numpy as np
import pytest

from spot_vision.charuco import (
    CalibrationOptions,
    CharucoBoardConfig,
    CharucoFrame,
    calibrate,
    write_calibration,
)
from spot_vision.config import load_calibration


def projected_views(noise=0.0, outlier=False):
    board = CharucoBoardConfig(
        squares_x=7,
        squares_y=5,
        square_length_m=0.04,
        marker_length_m=0.03,
        dictionary="DICT_4X4_50",
    )
    matrix = np.array([[880.0, 0.0, 620.0], [0.0, 890.0, 390.0], [0.0, 0.0, 1.0]])
    distortion = np.array([-0.12, 0.035, 0.001, -0.002, 0.005])
    # Independent object-point construction, rather than using Spot's helper.
    objects = np.array([[x * 0.04, y * 0.04, 0.0] for y in range(1, 5) for x in range(1, 7)])
    rng = np.random.default_rng(581)
    frames = []
    for i in range(20):
        rotation = np.array([-0.35 + 0.18 * (i % 5), -0.3 + 0.2 * (i // 5), 0.08 * (i % 3)])
        translation = np.array(
            [-0.23 + 0.08 * (i % 5), -0.15 + 0.08 * (i // 5), 0.7 + 0.07 * (i % 4)]
        )
        pixels = cv2.projectPoints(objects, rotation, translation, matrix, distortion)[0].reshape(
            -1, 2
        )
        pixels += rng.normal(0.0, noise, pixels.shape)
        if outlier and i == 19:
            pixels += rng.normal(0.0, 15.0, pixels.shape)
        frames.append(CharucoFrame(pixels, np.arange(24), (1280, 800), 17, 0.5, 200, 1))
    return board, matrix, distortion, frames


@pytest.mark.parametrize("model", ["plumb_bob", "rational"])
def test_real_opencv_calibration_recovers_independently_projected_intrinsics(model, tmp_path):
    board, matrix, distortion, frames = projected_views()
    options = CalibrationOptions(model=model, min_diversity=0.1, min_coverage=0.1)
    result, report = calibrate(frames, board, options)
    assert report.accepted and report.rms_reprojection_error_px < 0.001
    assert report.frames_used == 20 and report.rejected_frames == 0
    assert np.allclose(result["camera_matrix"], matrix, atol=0.1)
    # Rational coefficients are non-identifiable separately; compare their projection.
    objects = np.array([[x, y, 1.0] for x in [-0.4, 0, 0.4] for y in [-0.3, 0, 0.3]])
    expected = cv2.projectPoints(objects, np.zeros(3), np.zeros(3), matrix, distortion)[0]
    actual = cv2.projectPoints(
        objects,
        np.zeros(3),
        np.zeros(3),
        np.array(result["camera_matrix"]),
        np.array(result["distortion_coefficients"]),
    )[0]
    assert np.allclose(actual, expected, atol=0.1)
    result.update(camera_id="front", pixel_format="YUY2")
    path = tmp_path / "calibration.json"
    write_calibration(path, result)
    loaded = load_calibration(path)
    assert not loaded.provisional and loaded.width == 1280
    assert np.allclose(loaded.camera_matrix, matrix, atol=0.1)


def test_outlier_view_is_removed_and_intrinsics_are_refit():
    board, matrix, _, frames = projected_views(noise=0.05, outlier=True)
    result, report = calibrate(
        frames, board, CalibrationOptions(min_diversity=0.1, min_coverage=0.1)
    )
    assert report.accepted
    assert report.rejected_frames == 1 and report.frames_used == 19
    assert report.rms_reprojection_error_px < 0.15
    # Pixel noise couples principal point and lens coefficients; focal lengths
    # should recover more tightly than the principal point on this small board.
    recovered = np.array(result["camera_matrix"])
    assert np.allclose(recovered.diagonal()[:2], matrix.diagonal()[:2], atol=1.0)
    assert np.allclose(recovered[:2, 2], matrix[:2, 2], atol=3.0)


@pytest.mark.parametrize("gate", ["frames", "coverage", "diversity", "rms"])
def test_quality_gates_prevent_invalid_calibration(gate):
    board, _, _, frames = projected_views(noise=0.1 if gate == "rms" else 0)
    options = CalibrationOptions(min_diversity=0.1, min_coverage=0.1)
    if gate == "frames":
        frames = frames[:2]
    elif gate == "coverage":
        options = replace(options, min_coverage=0.9)
    elif gate == "diversity":
        frames = [frames[0]] * 20
        options = replace(options, min_diversity=0.9)
    else:
        options = replace(options, max_rms_px=0.001)
    result, report = calibrate(frames, board, options)
    assert result is None and not report.accepted


def test_atomic_save_failure_preserves_existing_calibration(tmp_path, monkeypatch):
    from spot_vision import charuco

    path = tmp_path / "calibration.json"
    path.write_text('{"previous":true}\n')

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(charuco.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        write_calibration(path, {"new": True})
    assert path.read_text() == '{"previous":true}\n'
    assert list(tmp_path.iterdir()) == [path]
