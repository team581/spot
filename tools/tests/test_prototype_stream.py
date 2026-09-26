from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "prototype_stream.py"
spec = importlib.util.spec_from_file_location("prototype_stream", SCRIPT)
stream = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = stream
spec.loader.exec_module(stream)


def test_index_contains_all_camera_ids_and_quotes_html_and_urls():
    hub = stream.StreamHub(["front", "rear / <one>"])
    try:
        page = hub.index()
        assert "front" in page and "rear / &lt;one&gt;" in page
        assert "/stream/rear%20%2F%20%3Cone%3E" in page
        assert "data-camera=\"rear / &lt;one&gt;\"" in page
    finally:
        hub.close()


def test_publish_is_idle_without_clients_and_latest_only_with_client():
    hub = stream.StreamHub(["front"])
    try:
        image = np.zeros((8, 16, 2), dtype=np.uint8)
        hub.publish("front", image, 1)
        assert not hub._pending
        with hub.cameras["front"].condition:
            hub.cameras["front"].clients = 1
        for sequence in range(100):
            hub.publish("front", image, sequence)
        with hub._pending_condition:
            assert len(hub._pending) <= 1
            if hub._pending:
                assert hub._pending["front"][1] == 99
    finally:
        hub.close()


def test_encoder_produces_bounded_jpeg_and_health_status():
    hub = stream.StreamHub(["front"])
    try:
        with hub.cameras["front"].condition:
            hub.cameras["front"].clients = 1
        image = np.zeros((720, 1280, 2), dtype=np.uint8)
        hub.publish("front", image, 7)
        deadline = time.monotonic() + 2
        while hub.cameras["front"].jpeg is None and time.monotonic() < deadline:
            time.sleep(.01)
        camera = hub.cameras["front"]
        assert camera.jpeg is not None and camera.jpeg.startswith(b"\xff\xd8")
        assert camera.sequence == 7
        health = json.loads(hub.health())
        assert health["cameras"]["front"]["fresh"]
    finally:
        hub.close()


def test_preview_preserves_shared_frame_orientation_for_each_camera():
    cv2 = pytest.importorskip("cv2")
    hub = stream.StreamHub(["left", "right"])
    try:
        image = np.full((64, 64, 2), 128, dtype=np.uint8)
        image[:32, :32, 0] = 40
        image[:32, 32:, 0] = 80
        image[32:, :32, 0] = 160
        image[32:, 32:, 0] = 220
        for camera in hub.cameras.values():
            with camera.condition:
                camera.clients = 1
        hub.publish("left", np.ascontiguousarray(image[::-1, ::-1]), 1)
        hub.publish("right", image, 1)
        deadline = time.monotonic() + 2
        while any(camera.jpeg is None for camera in hub.cameras.values()) and time.monotonic() < deadline:
            time.sleep(.01)
        left = cv2.imdecode(np.frombuffer(hub.cameras["left"].jpeg, np.uint8),
                            cv2.IMREAD_GRAYSCALE)
        right = cv2.imdecode(np.frombuffer(hub.cameras["right"].jpeg, np.uint8),
                             cv2.IMREAD_GRAYSCALE)
        assert left[8, 8] > 190 and right[8, 8] < 70
        assert left[56, 56] < 70 and right[56, 56] > 190
        assert np.mean(np.abs(left.astype(int) - np.rot90(right, 2).astype(int))) < 5
    finally:
        hub.close()


def test_http_index_health_unknown_camera_and_shutdown():
    hub = stream.StreamHub(["front"])
    server = hub.serve("127.0.0.1", 0)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            assert response.status == 200 and b"Buddy cameras" in response.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
            health = json.load(response)
            assert health["ready"] and "front" in health["cameras"]
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/stream/missing", timeout=2)
        assert error.value.code == 404
    finally:
        hub.close()
    assert not hub._worker.is_alive()


def test_port_conflict_is_reported():
    first = stream.StreamHub(["front"])
    second = stream.StreamHub(["rear"])
    server = first.serve("127.0.0.1", 0)
    try:
        with pytest.raises(OSError):
            second.serve("127.0.0.1", server.server_address[1])
    finally:
        first.close()
        second.close()


def test_mjpeg_client_receives_one_framed_image():
    hub = stream.StreamHub(["front"])
    server = hub.serve("127.0.0.1", 0)
    port = server.server_address[1]
    received = bytearray()

    def read_stream():
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/stream/front", timeout=3) as response:
            received.extend(response.readline())
            length = None
            while True:
                line = response.readline()
                received.extend(line)
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1])
                if line == b"\r\n":
                    break
            assert length is not None
            received.extend(response.read(length))

    reader = threading.Thread(target=read_stream)
    reader.start()
    try:
        deadline = time.monotonic() + 1
        while hub.cameras["front"].clients == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        hub.publish("front", np.zeros((8, 16, 2), dtype=np.uint8), 4)
        reader.join(timeout=3)
        assert not reader.is_alive()
        assert b"Content-Type: image/jpeg" in received
        assert b"X-Sequence: 4" in received
    finally:
        hub.close()
