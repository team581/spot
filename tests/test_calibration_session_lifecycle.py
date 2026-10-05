"""Session state, validation and race regressions without physical board IO."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import threading

import numpy as np
import pytest

from spot_vision import calibration_session as module
from spot_vision.charuco import CalibrationReport, CharucoFrame


@pytest.fixture
def session(tmp_path):
    session = module.CalibrationSession(["a", "b"], tmp_path)
    yield session
    session.close()
    assert not session.root.exists()


def sample():
    return CharucoFrame(np.array([[100, 100], [200, 100], [100, 200], [200, 200]], float),
                        np.array([0, 1, 14, 15]), (640, 480), 4, .4, 100, 1)


def test_start_stop_restart_are_scoped_and_preserve_source(session):
    camera = session.cameras["a"]
    camera.source = lambda: np.zeros((480, 640), np.uint8)
    camera.samples.append(sample())
    session.start("a", mode="auto")
    assert not session.cameras["b"].running
    session.stop("a")
    assert not camera.running
    session.restart("a")
    assert session.cameras["a"].running and session.cameras["a"].mode == "auto"
    assert session.cameras["a"].source is camera.source
    assert not session.cameras["a"].samples
    assert not session.cameras["b"].running


def test_invalid_mode_leaves_camera_state_unchanged(session):
    with pytest.raises(ValueError, match="mode"):
        session.start(mode="surprise")
    assert not any(camera.running for camera in session.cameras.values())


def test_configure_validates_before_replacing_session_settings(session):
    board, options = session.board, session.options
    with pytest.raises(ValueError):
        session.configure(replace(board, marker_length_m=board.square_length_m), options)
    assert session.board == board and session.options == options


def test_capture_rejects_missing_board_and_active_compute(session):
    assert not session.capture("a")
    camera = session.cameras["a"]
    camera.last_detection = sample()
    camera.calibrating = True
    assert not session.capture("a")
    with pytest.raises(RuntimeError, match="calibrating"):
        session.start("a")
    with pytest.raises(RuntimeError, match="already calibrating"):
        session.compute("a")
    assert not camera.samples


def test_failed_compute_clears_busy_state_and_exposes_error(session, monkeypatch):
    session.start("a")

    def fail(*_):
        raise RuntimeError("solver backend")

    monkeypatch.setattr(module, "calibrate", fail)
    with pytest.raises(RuntimeError, match="solver backend"):
        session.compute("a")
    camera = session.cameras["a"]
    assert not camera.running and not camera.calibrating
    assert "solver backend" in camera.error
    session.start("a")
    assert camera.error is None


@pytest.mark.parametrize("action", ["stop", "restart"])
def test_inflight_detection_cannot_mutate_stopped_or_replaced_camera(session, monkeypatch, action):
    entered, release = threading.Event(), threading.Event()

    def detect(*_):
        entered.set()
        assert release.wait(3)
        return sample()

    monkeypatch.setattr(module, "detect_frame", detect)
    session.cameras["a"].source = lambda: np.zeros((480, 640), np.uint8)
    session.start("a", mode="auto")
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(session.tick, "a")
        try:
            assert entered.wait(2)
            getattr(session, action)("a")
        finally:
            release.set()
        assert future.result(timeout=3) is None
    assert not session.cameras["a"].samples
    assert session.cameras["a"].last_detection is None


def test_slow_compute_does_not_block_other_camera_status_or_capture(session, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    report = CalibrationReport(True, "ok", 15, .8, .8, .2)

    def compute(*_):
        entered.set()
        assert release.wait(3)
        return {"test": True}, report

    monkeypatch.setattr(module, "calibrate", compute)
    session.cameras["b"].last_detection = sample()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(session.compute, "a")
        try:
            assert entered.wait(2)
            assert session.status()["a"]["calibrating"]
            assert session.capture("b")
        finally:
            release.set()
        assert future.result(timeout=3)[1] == report
    assert session.cameras["a"].report == report
    assert not session.cameras["a"].calibrating


def test_save_validates_every_camera_before_writing_any(session, tmp_path):
    session.cameras["a"].report = CalibrationReport(True, "ok", 15, .8, .8, .2)
    paths = {camera: str(tmp_path / f"{camera}.json") for camera in ["a", "b"]}
    with pytest.raises(ValueError, match="camera b"):
        session.save({"a": {}, "b": {}}, paths)
    assert not any((tmp_path / f"{camera}.json").exists() for camera in paths)


def test_save_override_requires_report_and_preserves_input(session, tmp_path):
    destination = tmp_path / "saved.json"
    with pytest.raises(ValueError):
        session.save({"a": {}}, {"a": str(destination)}, override=True)
    session.cameras["a"].report = CalibrationReport(False, "poor RMS", 15, .8, .8, 3)
    source = {"camera_id": "wrong", "value": 123}
    with pytest.raises(ValueError):
        session.save({"a": source}, {"a": str(destination)})
    session.save({"a": source}, {"a": str(destination)}, override=True)
    assert json.loads(destination.read_text())["camera_id"] == "a"
    assert source["camera_id"] == "wrong"


def test_status_is_json_safe_for_disjoint_corner_motion(session):
    camera = session.cameras["a"]
    camera.last_detection = sample()
    assert session.capture("a")
    camera.last_detection = replace(sample(), ids=np.array([20, 21, 34, 35]))
    assert session.capture("a")
    assert np.isinf(camera.motion)
    state = json.loads(json.dumps(session.status(), allow_nan=False))
    assert state["a"]["motion"] is None and state["a"]["frames"] == 2
