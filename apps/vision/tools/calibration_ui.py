"""Serve the local ChArUco wizard assets.

Use the same calibration API as the alpha daemon with direct camera sources.
The server never accepts filesystem paths from a browser.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from urllib.parse import urlsplit

from alpha_calibration import AlphaCalibration

from spot_vision.config import load_config


class OpenCVCameraSource:
    def __init__(self, camera):
        self.camera, self.handle = camera, None

    def __call__(self):
        import cv2

        if self.handle is None:
            device = (
                self.camera.selector.device
                or self.camera.selector.by_path
                or self.camera.selector.by_id
            )
            self.handle = cv2.VideoCapture(device)
            if not self.handle.isOpened():
                raise RuntimeError(f"camera busy/stop vision service: {self.camera.id}")
        ok, frame = self.handle.read()
        if not ok:
            raise RuntimeError(f"camera {self.camera.id} returned no frame")
        if self.camera.image_rotation_deg == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        return frame

    def close(self):
        if self.handle is not None:
            self.handle.release()
            self.handle = None


def main() -> None:
    parser = argparse.ArgumentParser(description="serve the Spot calibration wizard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--config", default="apps/vision/config/spot.json")
    parser.add_argument("--unsafe-bind", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not args.unsafe_bind:
        parser.error("non-loopback bind requires --unsafe-bind")
    directory = Path(__file__).resolve().parent
    config = load_config(args.config)
    sources = {c.id: OpenCVCameraSource(c) for c in config.cameras if c.enabled}
    controller = AlphaCalibration(
        config,
        lambda camera_id: sources[camera_id](),
        directory / ".calibration-sessions",
        directory / "calibration_ui.html",
    )

    class Handler(SimpleHTTPRequestHandler):
        def _reply(self, response):
            status, content_type, headers, body = response
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/calibration_ui.html":
                path = "/"
            response = controller.get(path)
            if response is not None:
                return self._reply(response)
            return super().do_GET()

        def do_POST(self):
            try:
                payload = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}"
                )
                if not isinstance(payload, dict):
                    raise ValueError("JSON object required")
            except (ValueError, json.JSONDecodeError):
                return self._reply((400, "application/json", {}, b'{"error":"invalid JSON"}'))
            response = controller.post(
                urlsplit(self.path).path, payload, self.headers.get("X-Calibration-Token", "")
            )
            self._reply(response)
            if urlsplit(self.path).path == "/api/session/close" and response[0] == 200:
                for source in sources.values():
                    source.close()

    server = ThreadingHTTPServer(
        (args.host, args.port), lambda *items: Handler(*items, directory=str(directory))
    )
    print(
        f"Calibration wizard: http://{args.host}:{args.port}/calibration_ui.html token={controller.token}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()
        for source in sources.values():
            source.close()
        server.server_close()


if __name__ == "__main__":
    main()
