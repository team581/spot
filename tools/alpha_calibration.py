"""ChArUco calibration web controller for the alpha daemon's shared frames."""
from __future__ import annotations

import json
import secrets
import copy
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from pathlib import Path
from urllib.parse import unquote

import numpy as np

from spot_vision.calibration_session import CalibrationSession
from spot_vision.charuco import CalibrationOptions, CharucoBoardConfig


def _json(status: int, value: object):
    return status, "application/json", {}, json.dumps(value, default=str).encode()


class AlphaCalibration:
    """Own calibration state while VisionService remains the sole camera owner."""

    def __init__(self, config, latest_frame, session_root: str | Path,
                 page: str | Path) -> None:
        self.config = config
        self.camera_ids = [camera.id for camera in config.cameras if camera.enabled]
        self._latest_frame = latest_frame
        self._root = Path(session_root)
        self._page = Path(page).read_bytes()
        self.preview_urls: dict[str, str] = {}
        self.token = secrets.token_urlsafe(32)
        self.session: CalibrationSession | None = None
        self.results: dict[str, dict] = {}
        self._jobs: set[tuple[str, str]] = set()
        self._jobs_lock = threading.RLock()

    def _source(self, camera_id: str):
        def read():
            import cv2
            raw = self._latest_frame(camera_id)
            if raw.ndim == 3 and raw.shape[2] == 2:
                return cv2.cvtColor(raw, cv2.COLOR_YUV2GRAY_YUY2)
            return raw
        return read

    def _camera_id(self, path: str) -> str | None:
        prefix, suffix = "/api/camera/", "/frame.jpg"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return None
        return unquote(path[len(prefix):-len(suffix)])

    def _storage_result(self, camera_id: str, result: dict) -> dict:
        """Convert corrected-frame intrinsics back to the configured raw sensor frame."""
        camera = self.config.camera(camera_id)
        stored = copy.deepcopy(result)
        stored["pixel_format"] = camera.format
        stored["calibrated_image_rotation_deg"] = camera.image_rotation_deg
        if camera.image_rotation_deg == 180:
            matrix = stored["camera_matrix"]
            matrix[0][2] = stored["width"] - 1 - matrix[0][2]
            matrix[1][2] = stored["height"] - 1 - matrix[1][2]
            distortion = stored["distortion_coefficients"]
            for index in (2, 3, 8, 9, 10, 11):
                if index < len(distortion):
                    distortion[index] = -distortion[index]
        return stored

    def get(self, path: str):
        if path == "/":
            return HTTPStatus.OK, "text/html; charset=utf-8", {}, self._page
        if path == "/api/cameras":
            return _json(HTTPStatus.OK, {
                "token": self.token,
                "cameras": self.camera_ids,
                "viewer_url": "/viewer",
                "preview_urls": self.preview_urls,
            })
        if path == "/api/session/status":
            return _json(HTTPStatus.OK, self._status())
        camera_id = self._camera_id(path)
        if camera_id is None:
            return None
        if camera_id not in self.camera_ids:
            return _json(HTTPStatus.NOT_FOUND, {"error": "unknown camera"})
        try:
            frame = self._source(camera_id)()
            if frame is None:
                raise RuntimeError(f"camera {camera_id} has not produced a frame yet")
            import cv2
            preview = frame.copy()
            ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if not ok:
                raise RuntimeError("JPEG encoder returned no image")
            return HTTPStatus.OK, "image/jpeg", {}, encoded.tobytes()
        except RuntimeError as exc:
            return _json(HTTPStatus.CONFLICT, {"error": str(exc)})

    def post(self, path: str, payload: dict, token: str):
        if token != self.token:
            return _json(HTTPStatus.FORBIDDEN, {"error": "calibration token required"})
        if "path" in payload or "paths" in payload:
            return _json(HTTPStatus.BAD_REQUEST, {"error": "filesystem paths are not accepted"})
        try:
            if path == "/api/session/start":
                self.close()
                sources = {camera_id: self._source(camera_id) for camera_id in self.camera_ids}
                self.session = CalibrationSession(self.camera_ids, self._root, sources)
                board_data = payload.get("board", {})
                option_data = payload.get("options", {})
                board = CharucoBoardConfig(**{
                    key: board_data[key] for key in asdict(CharucoBoardConfig()) if key in board_data})
                options = CalibrationOptions(**{
                    key: option_data[key] for key in asdict(CalibrationOptions()) if key in option_data})
                try:
                    self.session.configure(board, options)
                except (TypeError, ValueError, RuntimeError):
                    self.close()
                    raise
                self.results.clear()
                session = self.session
                threading.Thread(target=self._capture_loop, args=(session,),
                                 name="calibration-capture", daemon=True).start()
                return _json(HTTPStatus.OK, {
                    "session_id": self.session.id, "cameras": self.camera_ids})
            if path == "/api/session/close":
                self.close()
                return _json(HTTPStatus.OK, {"ok": True})
            if self.session is None or payload.get("session_id") != self.session.id:
                return _json(HTTPStatus.CONFLICT, {"error": "calibration session required"})
            camera_id = str(payload.get("camera_id", ""))
            if camera_id not in self.camera_ids:
                return _json(HTTPStatus.NOT_FOUND, {"error": "unknown camera"})
            if path == "/api/camera/start":
                self.session.start(camera_id, str(payload.get("mode", "manual")))
            elif path == "/api/camera/stop":
                self.session.stop(camera_id)
            elif path == "/api/camera/auto":
                self.session.start(camera_id, "auto" if payload.get("enabled", True) else "manual")
            elif path == "/api/camera/capture":
                # The background worker updates last_detection; ticking in auto
                # mode here would capture the same view twice.
                accepted = self.session.capture(camera_id)
                return _json(HTTPStatus.OK, {"accepted": accepted, "status": self._status()})
            elif path == "/api/camera/compute":
                self._compute_async(camera_id)
            elif path == "/api/camera/restart":
                with self._jobs_lock:
                    if (self.session.id, camera_id) in self._jobs:
                        raise RuntimeError("wait for calibration before restarting this camera")
                    self.session.restart(camera_id)
                    self.results.pop(camera_id, None)
            elif path == "/api/camera/save":
                result = self.results.get(camera_id)
                if result is None:
                    raise ValueError("compute a passing calibration before saving")
                camera = self.config.camera(camera_id)
                if camera.calibration is None:
                    raise ValueError("camera has no configured calibration path")
                self.session.save(
                    {camera_id: result}, {camera_id: str(camera.calibration)},
                    bool(payload.get("override", False)))
                return _json(HTTPStatus.OK, {"ok": True, "saved": camera_id})
            else:
                return _json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            return _json(HTTPStatus.OK, {"ok": True, "status": self._status()})
        except (KeyError, TypeError, ValueError) as exc:
            return _json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except RuntimeError as exc:
            return _json(HTTPStatus.CONFLICT, {"error": str(exc)})

    def _capture_loop(self, session: CalibrationSession) -> None:
        while self.session is session:
            started = time.monotonic()
            for camera_id in self.camera_ids:
                if self.session is not session:
                    return
                camera = session.cameras[camera_id]
                if not camera.running:
                    continue
                try:
                    session.tick(camera_id)
                    if self.session is session and session.ready(camera_id):
                        self._compute_async(camera_id, session)
                except Exception as exc:
                    camera.error = f"Capture unavailable: {exc}"
            time.sleep(max(.05, .5 - (time.monotonic() - started)))

    def _compute_async(self, camera_id: str, expected_session=None) -> None:
        with self._jobs_lock:
            session = self.session
            if session is None or (expected_session is not None and session is not expected_session):
                return
            camera = session.cameras[camera_id]
            key = (session.id, camera_id)
            if key in self._jobs:
                return
            self._jobs.add(key)
            self.results.pop(camera_id, None)

        def solve():
            try:
                result, _ = session.compute(camera_id)
                with self._jobs_lock:
                    if self.session is session and session.cameras[camera_id] is camera:
                        if result is not None:
                            self.results[camera_id] = self._storage_result(camera_id, result)
            except Exception as exc:
                camera.error = f"Calibration failed: {exc}"
            finally:
                with self._jobs_lock:
                    self._jobs.discard(key)
        threading.Thread(target=solve, name=f"calibrate-{camera_id}", daemon=True).start()

    def _status(self) -> dict:
        if self.session is None:
            return {"session_id": None, "cameras": {}}
        with self._jobs_lock:
            states = self.session.status()
            for camera_id, state in states.items():
                state["calibrating"] = state["calibrating"] or (self.session.id, camera_id) in self._jobs
            return {"session_id": self.session.id, "cameras": states}

    def close(self) -> None:
        with self._jobs_lock:
            session, self.session = self.session, None
            self.results.clear()
        if session is not None:
            session.close()
