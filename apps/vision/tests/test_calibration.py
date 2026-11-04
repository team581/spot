from __future__ import annotations

import copy

import cv2
import numpy as np

from spot_vision.calibration import validate_holdout
from spot_vision.charuco import CharucoBoardConfig, CharucoFrame, _object_points


def synthetic_views(noise=0.05):
    board = CharucoBoardConfig()
    matrix = np.array([[500, 0, 320], [0, 505, 240], [0, 0, 1]], float)
    ids = np.arange(196, dtype=np.int32)
    objects = _object_points(board, ids)
    frames = []
    for i in range(8):
        rvec = np.array([0.2 + (i % 3) * 0.15, -0.3 + (i % 4) * 0.15, 0.02 * i])
        tvec = np.array([-0.35 + (i % 4) * 0.16, -0.30 + (i // 4) * 0.3, 0.8 + (i % 3) * 0.2])
        points = cv2.projectPoints(objects, rvec, tvec, matrix, np.zeros(5))[0].reshape(-1, 2)
        points += np.random.default_rng(i).normal(0, noise, points.shape)
        frames.append(CharucoFrame(points, ids, (640, 480), 100, 0.5, 100, 1))
    intrinsics = {"camera_matrix": matrix.tolist(), "distortion_coefficients": [0] * 5}
    return board, frames, intrinsics


def test_holdout_fits_only_extrinsics_and_requires_new_diverse_views():
    board, frames, intrinsics = synthetic_views()
    original = copy.deepcopy(intrinsics)
    result = validate_holdout(frames, board, intrinsics)
    assert result["accepted"], result
    assert result["rms_px"] < 0.1
    assert intrinsics == original
    assert not validate_holdout(frames[:4], board, intrinsics)["accepted"]
    assert not validate_holdout([frames[0]] * 8, board, intrinsics)["accepted"]


def test_holdout_rejects_bad_lens_model_despite_fit_success():
    board, frames, intrinsics = synthetic_views()
    intrinsics["distortion_coefficients"] = [1.0, 0.2, 0.15, 0.15, 0]
    result = validate_holdout(frames, board, intrinsics)
    assert not result["accepted"]
    assert result["rms_px"] > 0.8


def calibration_runtime(tmp_path):
    from types import SimpleNamespace

    from spot_vision.calibration import CalibrationCamera, CalibrationManager
    from spot_vision.calibration_session import CameraSession

    config = SimpleNamespace(
        state=SimpleNamespace(data={}, generation="old"), require_eligible=lambda: None
    )
    runtime = SimpleNamespace(
        configuration=config,
        software={},
        workers={},
        validate_calibration=lambda _: None,
    )
    calibration = CalibrationManager(runtime)
    calibration._compatible = lambda _: None
    for identity in ("a", "b"):
        camera = CalibrationCamera(
            identity, "mode", 0, CameraSession(identity), CameraSession(identity), "old"
        )
        camera.intrinsics = {"calibrated_at": "untrusted-date"}
        camera.report, camera.validation = {"accepted": True}, {"accepted": True}
        calibration.cameras[identity] = camera
        runtime.workers[identity] = SimpleNamespace(readback={})
    return calibration, config


def test_activation_status_stays_responsive_while_durable_apply_is_pending(tmp_path):
    import threading
    from types import SimpleNamespace

    calibration, config = calibration_runtime(tmp_path)
    entered, release = threading.Event(), threading.Event()
    records = []

    def commit(group, revision, validate):
        records.extend(group)
        entered.set()
        assert release.wait(2)
        return SimpleNamespace(generation="applied")

    config.calibration_group = commit
    result = []
    worker = threading.Thread(
        target=lambda: result.append(
            calibration.command("apply", {"identities": ["a", "b"], "revision": "old"})
        )
    )
    worker.start()
    assert entered.wait(1)
    status = []
    reader = threading.Thread(target=lambda: status.append(calibration.status()))
    reader.start()
    reader.join(0.3)
    try:
        assert not reader.is_alive(), "HTTP status blocked behind native/durable activation"
        assert status[0]["applied_generation"] == ""
        assert all(
            record["saved_at"] is None and record["intrinsics"]["calibrated_at"] is None
            for record in records
        )
        assert calibration.cameras["a"].intrinsics["calibrated_at"] == "untrusted-date"
    finally:
        release.set()
        worker.join(2)
        reader.join(2)
    assert result[0]["applied_generation"] == "applied"


def test_start_all_validates_whole_capture_group_before_starting(tmp_path):
    import pytest

    calibration, _ = calibration_runtime(tmp_path)
    calibration.cameras["b"].intrinsics = None
    with pytest.raises(ValueError, match="Finish fitting"):
        calibration.command("start-all", {"revision": "old", "phase": "holdout"})
    assert not any(camera.running for camera in calibration.cameras.values())
    calibration.command("start-all", {"revision": "old", "phase": "fit"})
    assert all(camera.running and camera.automatic for camera in calibration.cameras.values())
    calibration.command("pause-all", {"revision": "old"})
    assert not any(camera.running for camera in calibration.cameras.values())


def test_activation_rejects_missing_intrinsics_before_committing_group(tmp_path):
    import pytest

    calibration, config = calibration_runtime(tmp_path)
    calibration.cameras["b"].intrinsics = None
    committed = []
    config.calibration_group = lambda *args: committed.append(args)
    with pytest.raises(ValueError, match="Every selected camera must pass"):
        calibration.command("apply", {"identities": ["a", "b"], "revision": "old"})
    assert not committed
    assert config.state.generation == "old"
