"""Disposable, unauthenticated MJPEG viewer for alpha hardware bring-up."""

from __future__ import annotations

import base64
import html
import json
import secrets
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

BOUNDARY = b"spot-frame"


class _Camera:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.jpeg: bytes | None = None
        self.sequence = 0
        self.revision = 0
        self.updated = 0.0
        self.clients = 0
        self.error = ""
        self.raw_image = None
        self.raw_sequence = 0
        self.telemetry = {}
        self.encoded_telemetry = {}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        connection, address = super().get_request()
        # Headers and small JPEGs must not wait for Nagle/delayed ACK timers.
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return connection, address


class StreamHub:
    """Fair, latest-only preview encoder shared by all browser clients."""

    def __init__(self, camera_ids: list[str], encode_fps: float = 15.0, calibration=None) -> None:
        self.cameras = {camera_id: _Camera() for camera_id in camera_ids}
        self.encode_fps = max(1.0, encode_fps)
        self._pending: dict[str, tuple[object, int, dict]] = {}
        self._last_encoded = {camera_id: 0.0 for camera_id in camera_ids}
        self._cursor = 0
        self._pending_condition = threading.Condition()
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._encode_loop, name="prototype-stream", daemon=True
        )
        self._server: _Server | None = None
        self._server_thread: threading.Thread | None = None
        self.calibration = calibration
        self._preview_hub: StreamHub | None = None
        self.service = None
        self.control_token = secrets.token_urlsafe(32)
        self._worker.start()

    def attach_service(self, service) -> None:
        self.service = service

    def camera_controls(self, camera_id, payload=None, token=""):
        from spot_vision.camera_controls import ControlError
        from spot_vision.capture import CameraError

        def response(status, value):
            return status, "application/json", {}, json.dumps(value).encode()

        if payload is not None and not secrets.compare_digest(token, self.control_token):
            return response(HTTPStatus.FORBIDDEN, {"error": "Refresh the dashboard before tuning"})
        workers = getattr(self.service, "capture_workers", [])
        worker = next((worker for worker in workers if worker.camera.id == camera_id), None)
        if worker is None:
            return response(HTTPStatus.NOT_FOUND, {"error": "Camera is disabled or unavailable"})
        try:
            controls = (
                worker.controls.read()
                if payload is None
                else worker.controls.set(payload.get("name"), payload.get("value"))
            )
            return response(
                HTTPStatus.OK,
                {"camera_id": camera_id, "controls": controls, "token": self.control_token},
            )
        except ValueError as exc:
            return response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (ControlError, CameraError) as exc:
            return response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})

    @staticmethod
    def _pose(candidate):
        if candidate is None:
            return None
        return {
            "translation": candidate.translation.tolist(),
            "quaternion": candidate.quaternion_wxyz.tolist(),
            "error_px": candidate.reprojection_error_px,
            "method": candidate.method.name,
            "tag_ids": list(candidate.tag_ids),
        }

    def publish_result(self, detected, solution, robot_pose) -> None:
        frame = detected.frame
        camera = self.cameras.get(frame.camera_id)
        if camera is None:
            return
        telemetry = {
            "sequence": frame.sequence,
            "width": frame.image.shape[1],
            "height": frame.image.shape[0],
            "detect_ms": detected.batch.detect_ms,
            "solve_ms": solution.solve_ms,
            "tags": [
                {
                    "id": tag.id,
                    "corners": tag.corners.tolist(),
                    "margin": tag.decision_margin,
                    "hamming": tag.hamming,
                    "used": tag.id in solution.used_tag_ids,
                    "reason": solution.rejection_reasons.get(tag.id),
                }
                for tag in detected.batch.detections
            ],
            "pose": self._pose(robot_pose),
            "candidates": [self._pose(candidate) for candidate in solution.candidates],
        }
        with camera.condition:
            camera.telemetry = telemetry
        # publish acquires the pending lock; the encoder takes that lock before
        # camera.condition. Holding camera.condition here can deadlock both.
        self.publish(frame.camera_id, frame.image, frame.sequence)

    def _project_axes(self, camera_id, telemetry) -> None:
        # Solve orientation per tag using active intrinsics. These axes remain
        # available without a field layout and never replace the published pose.
        solver = self.service.solvers.get(camera_id) if self.service else None
        if solver is not None and solver.calibration is not None:
            import cv2
            import numpy as np

            size = solver.tag_size_m * 0.75
            # The native tag plane is X right, Y down, Z into the tag.
            # The viewer legend promises right/up/out, so negate Y and Z.
            axes = np.array(
                [[0, 0, 0], [size, 0, 0], [0, -size, 0], [0, 0, -size]], dtype=np.float64
            )
            for tag, corners in (
                (tag, tag["corners"]) for tag in telemetry.get("tags", []) if "corners" in tag
            ):
                try:
                    result = cv2.solvePnPGeneric(
                        solver.local_corners,
                        np.asarray(corners, dtype=np.float64),
                        solver.camera_matrix,
                        solver.distortion,
                        flags=cv2.SOLVEPNP_IPPE_SQUARE,
                    )
                    if not result[0]:
                        continue
                    estimates = []
                    for rotation, translation in zip(result[1], result[2]):
                        if float(translation.reshape(-1)[2]) <= 0:
                            continue
                        projected = cv2.projectPoints(
                            solver.local_corners,
                            rotation,
                            translation,
                            solver.camera_matrix,
                            solver.distortion,
                        )[0].reshape(-1, 2)
                        error = float(
                            np.sqrt(np.mean(np.sum((projected - np.asarray(corners)) ** 2, axis=1)))
                        )
                        estimates.append((error, rotation, translation))
                    if estimates:
                        error, rotation, translation = min(estimates, key=lambda item: item[0])
                        points = cv2.projectPoints(
                            axes, rotation, translation, solver.camera_matrix, solver.distortion
                        )[0].reshape(-1, 2)
                        if np.isfinite(points).all():
                            tag["axes"] = points.round(2).tolist()
                            tag["orientation_error_px"] = error
                except (cv2.error, ValueError):
                    pass

    def dashboard_status(self) -> bytes:
        from spot_vision.config import load_calibration
        from spot_vision.pose import matrix_to_quaternion

        cameras = []
        configured = self.service.config.cameras if self.service else []
        for config in configured:
            saved, error = None, ""
            try:
                if config.calibration and config.calibration.exists():
                    saved = load_calibration(config.calibration)
                    saved.validate_for(config)
                    saved.for_image_rotation(config)
            except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
                error = str(exc)
                saved = None
            loaded = self.service.calibrations.get(config.id)
            corrected = saved.for_image_rotation(config) if saved else None
            camera = self.cameras.get(config.id)
            with camera.condition if camera else threading.RLock():
                age = time.monotonic() - camera.updated if camera and camera.updated else None
                cameras.append(
                    {
                        "id": config.id,
                        "enabled": config.enabled,
                        "width": config.width,
                        "height": config.height,
                        "fresh": age is not None and age < 2,
                        "age_s": age,
                        "calibration": "invalid"
                        if error
                        else "missing"
                        if saved is None
                        else "provisional"
                        if saved.provisional
                        else "calibrated",
                        "calibration_error": error,
                        "restart_required": config.enabled and corrected != loaded,
                        "active_calibration": "missing"
                        if loaded is None
                        else "provisional"
                        if loaded.provisional
                        else "calibrated",
                        "counters": self.service.counters[config.id].snapshot()
                        if config.enabled
                        else {},
                        "telemetry": camera.telemetry
                        if camera and age is not None and age < 2
                        else {},
                    }
                )
        layout = self.service.layout if self.service else None
        return json.dumps(
            {
                "cameras": cameras,
                "field_tags": [
                    {
                        "id": tag.id,
                        "translation": tag.field_from_tag[:3, 3].tolist(),
                        "quaternion": matrix_to_quaternion(tag.field_from_tag[:3, :3]).tolist(),
                    }
                    for tag in layout.tags.values()
                ]
                if layout
                else [],
                "field_available": layout is not None,
            },
            allow_nan=False,
        ).encode()

    def attach_calibration(self, calibration) -> None:
        self.calibration = calibration
        # Calibration consumes capture frames before AprilTag detection/pose.
        # Its encoder also avoids dashboard orientation solving entirely.
        if self._preview_hub is None:
            self._preview_hub = StreamHub(list(self.cameras), encode_fps=20)
        calibration.preview_urls = {
            camera_id: f"/preview/{quote(camera_id, safe='')}" for camera_id in self.cameras
        }

    def publish_capture(self, frame) -> None:
        if self._preview_hub is not None:
            self._preview_hub.publish(frame.camera_id, frame.image, frame.sequence)

    def latest_frame(self, camera_id: str):
        if self._preview_hub is not None:
            return self._preview_hub.latest_frame(camera_id)
        camera = self.cameras[camera_id]
        with camera.condition:
            if camera.raw_image is None:
                raise RuntimeError(f"camera {camera_id} has not produced a frame yet")
            return camera.raw_image.copy()

    def publish(self, camera_id: str, image: object, sequence: int) -> None:
        if camera_id not in self.cameras or self._stop.is_set():
            return
        camera = self.cameras[camera_id]
        with camera.condition:
            camera.raw_image = image
            camera.raw_sequence = sequence
            camera.updated = time.monotonic()
            camera.condition.notify_all()
            if camera.clients == 0:
                return
        with self._pending_condition:
            self._pending[camera_id] = (image, sequence, camera.telemetry)
            self._pending_condition.notify()

    def _next_ready(self) -> tuple[str, object, int, dict] | None:
        ids = list(self.cameras)
        now = time.monotonic()
        interval = 1.0 / self.encode_fps
        for offset in range(len(ids)):
            index = (self._cursor + offset) % len(ids)
            camera_id = ids[index]
            camera = self.cameras[camera_id]
            with camera.condition:
                active = camera.clients > 0
            if not active:
                self._pending.pop(camera_id, None)
                continue
            if camera_id in self._pending and now - self._last_encoded[camera_id] >= interval:
                image, sequence, telemetry = self._pending.pop(camera_id)
                self._cursor = (index + 1) % len(ids)
                self._last_encoded[camera_id] = now
                return camera_id, image, sequence, telemetry
        return None

    def _encode_loop(self) -> None:
        try:
            import cv2
        except ImportError:
            for camera in self.cameras.values():
                camera.error = "OpenCV is unavailable"
            return
        while not self._stop.is_set():
            with self._pending_condition:
                ready = self._next_ready()
                if ready is None:
                    self._pending_condition.wait(0.02)
                    continue
            camera_id, image, sequence, telemetry = ready
            camera = self.cameras[camera_id]
            try:
                # Work only on frames being previewed, in this bounded encoder
                # thread, so extra orientation solving cannot delay pose output.
                telemetry = dict(telemetry)
                telemetry["tags"] = [dict(tag) for tag in telemetry.get("tags", [])]
                self._project_axes(camera_id, telemetry)
                gray = (
                    cv2.cvtColor(image, cv2.COLOR_YUV2GRAY_YUY2)
                    if image.ndim == 3 and image.shape[2] == 2
                    else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    if image.ndim == 3
                    else image
                )
                height, width = gray.shape[:2]
                scale = min(1.0, 640 / width, 360 / height)
                if scale < 1.0:
                    gray = cv2.resize(
                        gray,
                        (max(1, round(width * scale)), max(1, round(height * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                ok, encoded = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if not ok:
                    raise RuntimeError("JPEG encoder returned no image")
                with camera.condition:
                    camera.jpeg = encoded.tobytes()
                    camera.sequence = sequence
                    camera.encoded_telemetry = telemetry
                    camera.revision += 1
                    camera.updated = time.monotonic()
                    camera.error = ""
                    camera.condition.notify_all()
            except Exception as exc:  # noqa: BLE001 - debug output must be isolated
                with camera.condition:
                    camera.error = str(exc)

    def serve(self, host: str = "0.0.0.0", port: int = 8765) -> _Server:
        hub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:
                return

            def _body(self, body: bytes, content_type: str) -> None:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _app_response(self, response) -> None:
                status, content_type, headers, body = response
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                url = urlsplit(self.path)
                path = url.path
                if path in {"/", "/dashboard"} and hub.service is not None:
                    self._body(
                        Path(__file__).with_name("alpha_dashboard.html").read_bytes(),
                        "text/html; charset=utf-8",
                    )
                    return
                if path == "/api/dashboard":
                    self._body(hub.dashboard_status(), "application/json")
                    return
                if path == "/api/camera-controls":
                    camera_id = parse_qs(url.query).get("id", [""])[0]
                    self._app_response(hub.camera_controls(camera_id))
                    return
                if hub.calibration is not None:
                    response = hub.calibration.get("/" if path == "/calibration" else path)
                    if response is not None:
                        self._app_response(response)
                        return
                if path == "/":
                    self._body(hub.index().encode(), "text/html; charset=utf-8")
                    return
                if path == "/viewer":
                    self._body(hub.index().encode(), "text/html; charset=utf-8")
                    return
                if path == "/healthz":
                    self._body(hub.health(), "application/json")
                    return
                if path.startswith("/stream/"):
                    camera = hub.cameras.get(unquote(path[len("/stream/") :]))
                    if camera is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._stream(camera)
                    return
                if path.startswith(("/snapshot/", "/inspection/", "/preview/")):
                    prefix = next(
                        prefix
                        for prefix in ("/snapshot/", "/inspection/", "/preview/")
                        if path.startswith(prefix)
                    )
                    encoder = hub._preview_hub if prefix == "/preview/" else hub
                    camera = encoder.cameras.get(unquote(path[len(prefix) :])) if encoder else None
                    if camera is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    try:
                        after = int(parse_qs(url.query).get("after", ["0"])[0])
                        if after < 0:
                            raise ValueError
                    except ValueError:
                        self.send_error(HTTPStatus.BAD_REQUEST)
                        return
                    self._snapshot(camera, after, prefix == "/inspection/", encoder)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                path = urlsplit(self.path).path
                if hub.calibration is None and path != "/api/camera-controls":
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 65536:
                        raise ValueError("Invalid request length")
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError("Expected a JSON object")
                except (ValueError, json.JSONDecodeError):
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/camera-controls":
                    self._app_response(
                        hub.camera_controls(
                            payload.get("camera_id"),
                            payload,
                            self.headers.get("X-Camera-Token", ""),
                        )
                    )
                    return
                response = hub.calibration.post(
                    urlsplit(self.path).path, payload, self.headers.get("X-Calibration-Token", "")
                )
                self._app_response(response)

            def _snapshot(
                self, camera: _Camera, after: int, metadata: bool = False, encoder=None
            ) -> None:
                encoder = encoder or hub
                with camera.condition:
                    camera.clients += 1
                with encoder._pending_condition:
                    encoder._pending_condition.notify()
                try:
                    deadline = time.monotonic() + 1.5
                    with camera.condition:
                        while camera.revision <= after and not encoder._stop.is_set():
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                break
                            camera.condition.wait(remaining)
                        frame, revision, sequence = (camera.jpeg, camera.revision, camera.sequence)
                        telemetry = camera.encoded_telemetry
                    if frame is None or revision <= after:
                        self.send_response(HTTPStatus.NO_CONTENT)
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        return
                    if metadata:
                        self._body(
                            json.dumps(
                                {
                                    "revision": revision,
                                    "sequence": sequence,
                                    "telemetry": telemetry,
                                    "jpeg": base64.b64encode(frame).decode("ascii"),
                                },
                                allow_nan=False,
                            ).encode(),
                            "application/json",
                        )
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Revision", str(revision))
                    self.send_header("X-Sequence", str(sequence))
                    self.end_headers()
                    self.wfile.write(frame)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with camera.condition:
                        camera.clients -= 1
                    with encoder._pending_condition:
                        encoder._pending_condition.notify()

            def _stream(self, camera: _Camera) -> None:
                with camera.condition:
                    camera.clients += 1
                with hub._pending_condition:
                    hub._pending_condition.notify()
                self.send_response(HTTPStatus.OK)
                self.send_header(
                    "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}"
                )
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                last_revision = 0
                try:
                    while not hub._stop.is_set():
                        with camera.condition:
                            while camera.revision == last_revision:
                                if hub._stop.is_set():
                                    break
                                camera.condition.wait(1.0)
                            frame, sequence, revision = (
                                camera.jpeg,
                                camera.sequence,
                                camera.revision,
                            )
                        if frame is None or revision == last_revision:
                            continue
                        last_revision = revision
                        header = (
                            b"--"
                            + BOUNDARY
                            + b"\r\nContent-Type: image/jpeg\r\n"
                            + f"Content-Length: {len(frame)}\r\n"
                            f"X-Sequence: {sequence}\r\n\r\n".encode()
                        )
                        self.wfile.write(header + frame + b"\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with camera.condition:
                        camera.clients = max(0, camera.clients - 1)
                    with hub._pending_condition:
                        hub._pending_condition.notify()

        self._server = _Server((host, port), Handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, name="prototype-http", daemon=True
        )
        self._server_thread.start()
        return self._server

    def health(self) -> bytes:
        now = time.monotonic()
        statuses = {}
        for camera_id, camera in self.cameras.items():
            with camera.condition:
                statuses[camera_id] = {
                    "fresh": camera.jpeg is not None and now - camera.updated < 2.0,
                    "sequence": camera.sequence,
                    "age_s": None if camera.updated == 0 else round(now - camera.updated, 3),
                    "clients": camera.clients,
                    "error": camera.error,
                }
        return (
            json.dumps(
                {"ready": self._server is not None, "cameras": statuses}, separators=(",", ":")
            )
            + "\n"
        ).encode()

    def index(self) -> str:
        cards = "".join(
            f'<section data-camera="{html.escape(camera_id, quote=True)}">'
            f"<header><h2>{html.escape(camera_id)}</h2><span>Waiting for frames</span></header>"
            f'<canvas data-url="/snapshot/{quote(camera_id, safe="")}" '
            f'role="img" aria-label="Live {html.escape(camera_id, quote=True)} camera stream">'
            f"</canvas></section>"
            for camera_id in self.cameras
        )
        return (
            "<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Spot cameras</title><style>"
            ":root{color-scheme:dark}body{background:#0b0d10;color:#f3f5f7;"
            "font:16px system-ui,sans-serif;margin:1rem}"
            "main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:1rem}"
            "section{background:#15191f;border:1px solid #343b46;border-radius:.5rem;overflow:hidden}"
            "header{align-items:center;display:flex;justify-content:space-between;padding:.7rem 1rem}"
            "h2{font-size:1rem;margin:0}span{color:#aeb7c3;font-size:.875rem}"
            "canvas{background:#050607;display:block;width:100%;aspect-ratio:16/9;object-fit:contain}"
            "</style></head><body><main>" + cards + "</main><script>"
            "const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));"
            "async function show(canvas){let revision=0;const context=canvas.getContext('2d');"
            "for(;;){try{const controller=new AbortController();"
            "const timer=setTimeout(()=>controller.abort(),3000);let response;"
            "try{response=await fetch(canvas.dataset.url+'?after='+revision,"
            "{cache:'no-store',signal:controller.signal});}finally{clearTimeout(timer);}"
            "if(response.status===204)continue;if(!response.ok)throw Error(response.status);"
            "const next=Number(response.headers.get('X-Revision'));"
            "const bitmap=await createImageBitmap(await response.blob());"
            "canvas.width=bitmap.width;canvas.height=bitmap.height;"
            "context.drawImage(bitmap,0,0);bitmap.close();revision=next;"
            "}catch(error){await pause(500);}}}"
            "document.querySelectorAll('canvas[data-url]').forEach(show);"
            "async function update(){try{const r=await fetch('/healthz',{cache:'no-store'});"
            "const h=await r.json();document.querySelectorAll('[data-camera]').forEach(s=>{"
            "const c=h.cameras[s.dataset.camera],x=s.querySelector('span');"
            "x.textContent=!c?'Unavailable':c.error?c.error:c.fresh?'Live · frame '+c.sequence:"
            "c.sequence?'Stale · frame '+c.sequence:'Waiting for frames';});}catch(e){}}"
            "update();setInterval(update,1000);</script></body></html>"
        )

    def close(self) -> None:
        if self._preview_hub is not None:
            self._preview_hub.close()
        self._stop.set()
        with self._pending_condition:
            self._pending_condition.notify_all()
        for camera in self.cameras.values():
            with camera.condition:
                camera.condition.notify_all()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._server_thread is not None:
            self._server_thread.join(timeout=2)
        self._worker.join(timeout=2)
