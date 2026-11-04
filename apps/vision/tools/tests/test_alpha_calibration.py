from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "alpha_calibration.py"
spec = importlib.util.spec_from_file_location("alpha_calibration", SCRIPT)
calibration = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = calibration
spec.loader.exec_module(calibration)


def wait_until(predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


class Camera:
    def __init__(self, camera_id: str, destination: Path):
        self.id = camera_id
        self.enabled = True
        self.calibration = destination
        self.format = "MJPEG"
        self.image_rotation_deg = 180


class Config:
    def __init__(self, camera: Camera):
        self.cameras = (camera,)

    def camera(self, camera_id: str):
        assert camera_id == self.cameras[0].id
        return self.cameras[0]


def decode(response):
    return response[0], json.loads(response[3])


def test_controller_bootstrap_auth_shared_frame_and_cleanup(tmp_path):
    page = tmp_path / "ui.html"
    page.write_text("<h1>Calibration</h1>")
    camera = Camera("front", tmp_path / "front.json")
    raw = np.zeros((48, 64, 2), dtype=np.uint8)
    app = calibration.AlphaCalibration(
        Config(camera), lambda camera_id: raw.copy(), tmp_path / "sessions", page
    )

    assert app.get("/")[3] == b"<h1>Calibration</h1>"
    status, body = decode(app.get("/api/cameras"))
    assert status == 200 and body["cameras"] == ["front"] and body["viewer_url"] == "/viewer"
    # Preview is available before capture starts, without creating a session.
    preview = app.get("/api/camera/front/frame.jpg")
    assert preview[0] == 200 and preview[3].startswith(b"\xff\xd8")
    assert app.session is None
    assert decode(app.post("/api/session/start", {}, "wrong"))[0] == 403

    status, body = decode(
        app.post(
            "/api/session/start",
            {
                "board": {"squares_x": 6, "squares_y": 4},
                "options": {"min_frames": 8},
            },
            app.token,
        )
    )
    assert status == 200
    session_id = body["session_id"]
    assert app.session.board.squares_x == 6 and app.session.options.min_frames == 8
    assert (
        decode(
            app.post(
                "/api/camera/start", {"session_id": session_id, "camera_id": "front"}, app.token
            )
        )[0]
        == 200
    )
    frame = app.get("/api/camera/front/frame.jpg")
    assert frame[0] == 200 and frame[1] == "image/jpeg" and frame[3].startswith(b"\xff\xd8")
    assert (
        decode(
            app.post(
                "/api/camera/stop", {"session_id": session_id, "camera_id": "front"}, app.token
            )
        )[0]
        == 200
    )
    app.session.cameras["front"].last_frame = None
    assert app.get("/api/camera/front/frame.jpg")[0] == 200
    assert not app.session.cameras["front"].running
    assert (
        decode(
            app.post(
                "/api/camera/capture", {"session_id": session_id, "camera_id": "front"}, app.token
            )
        )[1]["accepted"]
        is False
    )
    assert (
        decode(
            app.post(
                "/api/camera/start", {"session_id": session_id, "camera_id": "missing"}, app.token
            )
        )[0]
        == 404
    )
    assert (
        decode(
            app.post(
                "/api/camera/start",
                {"session_id": session_id, "camera_id": "front", "path": "/tmp/nope"},
                app.token,
            )
        )[0]
        == 400
    )
    assert decode(app.post("/api/session/close", {"session_id": session_id}, app.token))[0] == 200
    assert app.session is None


def test_preview_reports_missing_camera_frames_without_a_session(tmp_path):
    page = tmp_path / "ui.html"
    page.write_text("ok")

    def unavailable(_camera_id):
        raise RuntimeError("camera front has not produced a frame yet")

    app = calibration.AlphaCalibration(
        Config(Camera("front", tmp_path / "front.json")), unavailable, tmp_path / "sessions", page
    )
    status, body = decode(app.get("/api/camera/front/frame.jpg"))
    assert status == 409 and "has not produced a frame" in body["error"]
    assert app.session is None


def test_compute_converts_corrected_intrinsics_to_raw_and_save_uses_config_path(tmp_path):
    from spot_vision.charuco import CalibrationReport

    page = tmp_path / "ui.html"
    page.write_text("ok")
    destination = tmp_path / "configured.json"
    app = calibration.AlphaCalibration(
        Config(Camera("front", destination)),
        lambda _camera_id: np.zeros((48, 64, 2), dtype=np.uint8),
        tmp_path / "sessions",
        page,
    )
    _, started = decode(app.post("/api/session/start", {}, app.token))
    session_id = started["session_id"]
    report = CalibrationReport(True, "calibration passed", 15, 0.5, 0.75, 0.4)
    app.session.cameras["front"].report = report
    solved = {
        "width": 1280,
        "height": 720,
        "camera_matrix": [[1000.0, 0.0, 700.0], [0.0, 1000.0, 400.0], [0.0, 0.0, 1.0]],
        "distortion_coefficients": [0.1, 0.2, 0.03, -0.04, 0.5],
    }
    app.session.compute = lambda _camera_id: (solved, report)
    status, body = decode(
        app.post("/api/camera/compute", {"session_id": session_id, "camera_id": "front"}, app.token)
    )
    assert status == 200
    wait_until(lambda: "front" in app.results)
    result = app.results["front"]
    assert result["pixel_format"] == "MJPEG"
    assert result["camera_matrix"][0][2] == 579.0
    assert result["camera_matrix"][1][2] == 319.0
    assert result["distortion_coefficients"][2:4] == [-0.03, 0.04]
    status, _ = decode(
        app.post("/api/camera/save", {"session_id": session_id, "camera_id": "front"}, app.token)
    )
    assert status == 200 and destination.exists()
    saved = json.loads(destination.read_text())
    assert saved["camera_id"] == "front" and saved["pixel_format"] == "MJPEG"


def test_auto_preview_updates_capture_and_status_then_compute_pauses(tmp_path):
    from spot_vision.charuco import CharucoBoardConfig, make_board

    page = tmp_path / "ui.html"
    page.write_text("ok")
    image = make_board(CharucoBoardConfig()).generateImage((800, 800), marginSize=20)
    app = calibration.AlphaCalibration(
        Config(Camera("front", tmp_path / "front.json")),
        lambda _: image,
        tmp_path / "sessions",
        page,
    )
    _, started = decode(app.post("/api/session/start", {}, app.token))
    payload = {"session_id": started["session_id"], "camera_id": "front", "mode": "auto"}
    assert decode(app.post("/api/camera/start", payload, app.token))[0] == 200
    for _ in range(3):
        assert app.get("/api/camera/front/frame.jpg")[0] == 200
    wait_until(lambda: len(app.session.cameras["front"].samples) == 1)
    state = decode(app.get("/api/session/status"))[1]["cameras"]["front"]
    assert state["frames"] == 1 and state["detected"]
    assert state["mode"] == "auto" and state["coverage_particles"]
    assert state["coverage_good_fraction"] == 0
    app.results["front"] = {"stale": True}
    _, result = decode(app.post("/api/camera/compute", payload, app.token))
    wait_until(lambda: not app._jobs)
    assert not app.session.cameras["front"].report.accepted
    assert not app.session.cameras["front"].running
    assert "front" not in app.results
    app.close()


def test_board_dictionary_capacity_failure_cleans_up_session(tmp_path):
    page = tmp_path / "ui.html"
    page.write_text("ok")
    app = calibration.AlphaCalibration(
        Config(Camera("front", tmp_path / "front.json")),
        lambda _: np.zeros((48, 64), dtype=np.uint8),
        tmp_path / "sessions",
        page,
    )
    status, body = decode(
        app.post(
            "/api/session/start",
            {
                "board": {"dictionary": "DICT_4X4_50"},
            },
            app.token,
        )
    )
    assert status == 400 and "needs 112 unique markers" in body["error"]
    assert app.session is None
    assert not list((tmp_path / "sessions").iterdir())


def test_compute_is_nonblocking_and_restart_is_scoped(tmp_path, monkeypatch):
    import threading

    import spot_vision.calibration_session as module
    from spot_vision.charuco import CalibrationReport

    page = tmp_path / "ui.html"
    page.write_text("ok")
    config = Config(Camera("front", tmp_path / "front.json"))
    config.cameras += (Camera("rear", tmp_path / "rear.json"),)
    app = calibration.AlphaCalibration(
        config, lambda _: np.zeros((48, 64), dtype=np.uint8), tmp_path / "sessions", page
    )
    _, started = decode(app.post("/api/session/start", {}, app.token))
    entered, release = threading.Event(), threading.Event()

    def slow_solve(*_):
        entered.set()
        assert release.wait(4)
        return None, CalibrationReport(False, "needs views", 0, 0, 0, None)

    monkeypatch.setattr(module, "calibrate", slow_solve)
    payload = {"session_id": started["session_id"], "camera_id": "front"}
    try:
        assert decode(app.post("/api/camera/compute", payload, app.token))[0] == 200
        assert entered.wait(2)
        state = decode(app.get("/api/session/status"))[1]["cameras"]
        assert state["front"]["calibrating"] and not state["rear"]["calibrating"]
        assert app.get("/api/camera/front/frame.jpg")[0] == 200
        assert decode(app.post("/api/camera/restart", payload, app.token))[0] == 409
    finally:
        release.set()
    wait_until(lambda: not app._jobs)
    rear = app.session.cameras["rear"]
    app.results["front"] = {"old": True}
    assert decode(app.post("/api/camera/restart", payload, app.token))[0] == 200
    assert app.session.cameras["rear"] is rear
    assert app.session.cameras["front"].report is None
    assert app.session.cameras["front"].running
    assert "front" not in app.results
    app.close()


def test_automatic_compute_runs_when_ready(tmp_path, monkeypatch):
    from spot_vision.charuco import CalibrationReport

    page = tmp_path / "ui.html"
    page.write_text("ok")
    app = calibration.AlphaCalibration(
        Config(Camera("front", tmp_path / "front.json")),
        lambda _: np.zeros((48, 64), dtype=np.uint8),
        tmp_path / "sessions",
        page,
    )
    _, started = decode(app.post("/api/session/start", {}, app.token))
    called = []

    def solve(camera_id):
        called.append(camera_id)
        camera = app.session.cameras[camera_id]
        camera.running = False
        camera.report = CalibrationReport(False, "needs views", 15, 0.5, 1, 2)
        return None, camera.report

    monkeypatch.setattr(app.session, "compute", solve)
    monkeypatch.setattr(app.session, "ready", lambda _: True)
    payload = {"session_id": started["session_id"], "camera_id": "front", "mode": "auto"}
    app.post("/api/camera/start", payload, app.token)
    wait_until(lambda: bool(called))
    wait_until(lambda: not app._jobs)
    assert called == ["front"]
    app.close()
