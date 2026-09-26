"""Disposable, unauthenticated MJPEG viewer for alpha hardware bring-up."""
from __future__ import annotations

import html
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

BOUNDARY = b"buddy-frame"


class _Camera:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.jpeg: bytes | None = None
        self.sequence = 0
        self.updated = 0.0
        self.clients = 0
        self.error = ""


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StreamHub:
    """Fair, latest-only preview encoder shared by all browser clients."""

    def __init__(self, camera_ids: list[str], encode_fps: float = 10.0) -> None:
        self.cameras = {camera_id: _Camera() for camera_id in camera_ids}
        self.encode_fps = max(1.0, encode_fps)
        self._pending: dict[str, tuple[object, int]] = {}
        self._last_encoded = {camera_id: 0.0 for camera_id in camera_ids}
        self._cursor = 0
        self._pending_condition = threading.Condition()
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._encode_loop, name="prototype-stream", daemon=True)
        self._server: _Server | None = None
        self._server_thread: threading.Thread | None = None
        self._worker.start()

    def publish(self, camera_id: str, image: object, sequence: int) -> None:
        if camera_id not in self.cameras or self._stop.is_set():
            return
        camera = self.cameras[camera_id]
        with camera.condition:
            if camera.clients == 0:
                return
        with self._pending_condition:
            self._pending[camera_id] = (image, sequence)
            self._pending_condition.notify()

    def _next_ready(self) -> tuple[str, object, int] | None:
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
                image, sequence = self._pending.pop(camera_id)
                self._cursor = (index + 1) % len(ids)
                self._last_encoded[camera_id] = now
                return camera_id, image, sequence
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
                    self._pending_condition.wait(.02)
                    continue
            camera_id, image, sequence = ready
            camera = self.cameras[camera_id]
            try:
                gray = cv2.cvtColor(image, cv2.COLOR_YUV2GRAY_YUY2)
                height, width = gray.shape[:2]
                scale = min(1.0, 640 / width, 360 / height)
                if scale < 1.0:
                    gray = cv2.resize(
                        gray, (max(1, round(width * scale)), max(1, round(height * scale))),
                        interpolation=cv2.INTER_AREA)
                ok, encoded = cv2.imencode(
                    ".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if not ok:
                    raise RuntimeError("JPEG encoder returned no image")
                with camera.condition:
                    camera.jpeg = encoded.tobytes()
                    camera.sequence = sequence
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

            def do_GET(self) -> None:
                path = urlsplit(self.path).path
                if path == "/":
                    self._body(hub.index().encode(), "text/html; charset=utf-8")
                    return
                if path == "/healthz":
                    self._body(hub.health(), "application/json")
                    return
                if path.startswith("/stream/"):
                    camera = hub.cameras.get(unquote(path[len("/stream/"):]))
                    if camera is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._stream(camera)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def _stream(self, camera: _Camera) -> None:
                with camera.condition:
                    camera.clients += 1
                with hub._pending_condition:
                    hub._pending_condition.notify()
                self.send_response(HTTPStatus.OK)
                self.send_header(
                    "Content-Type",
                    f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                last_sequence = -1
                try:
                    while not hub._stop.is_set():
                        with camera.condition:
                            while (camera.jpeg is None or camera.sequence == last_sequence):
                                if hub._stop.is_set():
                                    break
                                camera.condition.wait(1.0)
                            frame, sequence = camera.jpeg, camera.sequence
                        if frame is None or sequence == last_sequence:
                            continue
                        last_sequence = sequence
                        header = (
                            b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\n"
                            + f"Content-Length: {len(frame)}\r\n"
                              f"X-Sequence: {sequence}\r\n\r\n".encode())
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
            target=self._server.serve_forever, name="prototype-http", daemon=True)
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
        return (json.dumps({"ready": self._server is not None, "cameras": statuses},
                           separators=(",", ":")) + "\n").encode()

    def index(self) -> str:
        cards = "".join(
            f'<section data-camera="{html.escape(camera_id, quote=True)}">'
            f'<header><h2>{html.escape(camera_id)}</h2><span>Waiting for frames</span></header>'
            f'<img src="/stream/{quote(camera_id, safe="")}" '
            f'alt="Live {html.escape(camera_id, quote=True)} camera stream"></section>'
            for camera_id in self.cameras)
        return (
            "<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Buddy cameras</title><style>"
            ":root{color-scheme:dark}body{background:#0b0d10;color:#f3f5f7;"
            "font:16px system-ui,sans-serif;margin:1rem}"
            "main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:1rem}"
            "section{background:#15191f;border:1px solid #343b46;border-radius:.5rem;overflow:hidden}"
            "header{align-items:center;display:flex;justify-content:space-between;padding:.7rem 1rem}"
            "h2{font-size:1rem;margin:0}span{color:#aeb7c3;font-size:.875rem}"
            "img{background:#050607;display:block;width:100%;aspect-ratio:16/9;object-fit:contain}"
            "</style></head><body><main>" + cards + "</main><script>"
            "async function update(){try{const r=await fetch('/healthz',{cache:'no-store'});"
            "const h=await r.json();document.querySelectorAll('[data-camera]').forEach(s=>{"
            "const c=h.cameras[s.dataset.camera],x=s.querySelector('span');"
            "x.textContent=!c?'Unavailable':c.error?c.error:c.fresh?'Live · frame '+c.sequence:"
            "c.sequence?'Stale · frame '+c.sequence:'Waiting for frames';});}catch(e){}}"
            "update();setInterval(update,1000);</script></body></html>")

    def close(self) -> None:
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
