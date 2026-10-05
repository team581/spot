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
        assert "/snapshot/rear%20%2F%20%3Cone%3E" in page
        assert "data-camera=\"rear / &lt;one&gt;\"" in page
    finally:
        hub.close()


def test_publish_is_idle_without_clients_and_latest_only_with_client():
    hub = stream.StreamHub(["front"])
    try:
        image = np.zeros((8, 16, 2), dtype=np.uint8)
        hub.publish("front", image, 1)
        assert not hub._pending
        assert np.array_equal(hub.latest_frame("front"), image)
        assert hub.latest_frame("front") is not image
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


def test_result_publish_releases_camera_lock_before_waiting_for_encoder():
    from spot_vision.models import DetectionBatch, DetectedFrame, FramePacket, PoseSolution

    hub = stream.StreamHub(["front"])
    camera = hub.cameras["front"]
    packet = FramePacket("front", 3, 3, 0, time.monotonic_ns(),
                         np.zeros((8, 16, 2), dtype=np.uint8))
    detected = DetectedFrame(packet, DetectionBatch((), 0), 0)
    publisher = threading.Thread(target=hub.publish_result,
                                 args=(detected, PoseSolution(), None))
    try:
        with hub._pending_condition:
            camera.clients = 1
            publisher.start()
            deadline = time.monotonic() + 1
            while camera.telemetry.get("sequence") != 3 and time.monotonic() < deadline:
                time.sleep(.005)
            assert camera.telemetry.get("sequence") == 3
            # The encoder holds the pending lock while reading camera state.
            # It must be able to take the camera lock as publish waits here.
            acquired = camera.condition.acquire(timeout=.5)
            if acquired:
                camera.condition.release()
            assert acquired
        publisher.join(1)
        assert not publisher.is_alive()
    finally:
        publisher.join(1)
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
            assert response.status == 200 and b"Spot cameras" in response.read()
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


def test_snapshot_waits_for_new_frame_and_keeps_revision_independent_of_capture_sequence():
    hub = stream.StreamHub(["left", "right"])
    server = hub.serve("127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def snapshot(after: int):
        with urllib.request.urlopen(f"{base}/snapshot/right?after={after}", timeout=3) as response:
            return response.status, response.headers, response.read()

    result = []
    reader = threading.Thread(target=lambda: result.append(snapshot(0)))
    reader.start()
    try:
        deadline = time.monotonic() + 1
        while hub.cameras["right"].clients == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        assert hub.cameras["right"].clients == 1
        assert hub.cameras["left"].clients == 0
        image = np.zeros((8, 16, 2), dtype=np.uint8)
        hub.publish("right", image, 42)
        reader.join(timeout=3)
        assert not reader.is_alive()
        status, headers, body = result[0]
        assert status == 200 and body.startswith(b"\xff\xd8")
        assert headers["X-Revision"] == "1"
        assert headers["X-Sequence"] == "42"
        status, _, body = snapshot(1)
        assert status == 204 and body == b""
        assert hub.cameras["right"].jpeg is not None

        result.clear()
        reader = threading.Thread(target=lambda: result.append(snapshot(1)))
        reader.start()
        deadline = time.monotonic() + 1
        while hub.cameras["right"].clients == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        # A capture restart can reset its sequence without confusing the viewer.
        hub.publish("right", image, 1)
        reader.join(timeout=3)
        assert not reader.is_alive()
        assert result[0][1]["X-Revision"] == "2"
        assert result[0][1]["X-Sequence"] == "1"
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"{base}/snapshot/right?after=-1", timeout=2)
        assert error.value.code == 400
    finally:
        hub.close()


def test_calibration_preview_uses_capture_while_result_pipeline_is_stalled():
    from types import SimpleNamespace
    from spot_vision.models import FramePacket

    hub = stream.StreamHub(["front"])
    calibration = SimpleNamespace(preview_urls={}, get=lambda _: None)
    hub.attach_calibration(calibration)
    preview = hub._preview_hub
    server = hub.serve("127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    result = []

    def read_preview(after):
        with urllib.request.urlopen(f"{base}/preview/front?after={after}", timeout=3) as response:
            result.append((response.headers, response.read()))

    try:
        assert calibration.preview_urls == {"front": "/preview/front"}
        for sequence in (12, 13):
            reader = threading.Thread(target=read_preview, args=(sequence - 12,))
            reader.start()
            deadline = time.monotonic() + 1
            while preview.cameras["front"].clients == 0 and time.monotonic() < deadline:
                time.sleep(.005)
            image = np.full((8, 16, 2), sequence, dtype=np.uint8)
            packet = FramePacket("front", sequence, sequence, 0, time.monotonic_ns(), image)
            hub.publish_capture(packet)
            reader.join(2)
            assert not reader.is_alive()
            assert result[-1][0]["X-Sequence"] == str(sequence)
            assert result[-1][1].startswith(b"\xff\xd8")
            assert np.array_equal(hub.latest_frame("front"), image)
            assert hub.latest_frame("front") is not image

        # Older processed frames cannot rewind calibration's capture source.
        hub.publish("front", np.zeros_like(image), 1)
        assert np.array_equal(hub.latest_frame("front"), image)
        assert hub.cameras["front"].jpeg is None
        assert preview.cameras["front"].encoded_telemetry.get("tags", []) == []
    finally:
        hub.close()
    assert not preview._worker.is_alive()


def dashboard_service(tmp_path):
    from types import SimpleNamespace
    from spot_vision.config import Calibration, CameraConfig, CameraSelector, DetectorConfig
    from spot_vision.models import CameraCounters
    from spot_vision.pose import PoseSolver
    calibration = Calibration('front', 640, 360, 'MJPEG',
                              ((500., 0., 320.), (0., 500., 180.), (0., 0., 1.)),
                              (0., 0., 0., 0., 0.))
    camera = CameraConfig('front', True, CameraSelector(device='/dev/null'), 'MJPEG',
                          640, 360, 30, None, None, False, tmp_path / 'front.json',
                          0, 1, DetectorConfig())
    return SimpleNamespace(config=SimpleNamespace(cameras=(camera,)),
                           calibrations={'front': calibration}, layout=None,
                           counters={'front': CameraCounters()},
                           solvers={'front': PoseSolver(calibration, None, .1651)})


def test_orientation_axes_are_projected_from_active_intrinsics_without_field_layout(tmp_path):
    import cv2
    from spot_vision.models import Detection, DetectionBatch, DetectedFrame, FramePacket, PoseSolution
    hub = stream.StreamHub(['front'])
    service = dashboard_service(tmp_path)
    hub.attach_service(service)
    solver = service.solvers['front']
    rotation = np.array([2.85, .18, .12])
    translation = np.array([.08, -.03, .8])
    corners = cv2.projectPoints(solver.local_corners, rotation, translation,
                               solver.camera_matrix, solver.distortion)[0].reshape(-1, 2)
    packet = FramePacket('front', 3, 3, 0, time.monotonic_ns(),
                         np.zeros((360, 640), dtype=np.uint8))
    try:
        hub.cameras['front'].clients = 1
        hub.publish_result(DetectedFrame(packet, DetectionBatch((Detection(7, corners),), 2), 3),
                           PoseSolution(), None)
        deadline = time.monotonic() + 2
        while hub.cameras['front'].jpeg is None and time.monotonic() < deadline:
            time.sleep(.01)
        data = hub.cameras['front'].encoded_telemetry
        assert data['pose'] is None and data['sequence'] == 3
        tag = data['tags'][0]
        assert tag['orientation_error_px'] < .001
        axes = np.array([[0, 0, 0], [.1651*.75, 0, 0], [0, -.1651*.75, 0],
                         [0, 0, -.1651*.75]])
        expected = cv2.projectPoints(axes, rotation, translation, solver.camera_matrix,
                                     solver.distortion)[0].reshape(-1, 2)
        assert np.allclose(tag['axes'], expected, atol=.02)
        solver.calibration = None
        hub.publish_result(DetectedFrame(packet, DetectionBatch((Detection(7, corners),), 2), 3),
                           PoseSolution(), None)
        assert 'axes' not in hub.cameras['front'].telemetry['tags'][0]
    finally:
        hub.close()


def test_upright_tag_overlay_axes_point_right_and_up(tmp_path):
    import cv2
    hub = stream.StreamHub(['front'])
    service = dashboard_service(tmp_path)
    hub.attach_service(service)
    solver = service.solvers['front']
    rotation = np.array([.08, .04, 0.])
    translation = np.array([.03, -.02, 1.])
    corners = cv2.projectPoints(solver.local_corners, rotation, translation,
                               solver.camera_matrix, solver.distortion)[0].reshape(-1, 2)
    telemetry = {'tags': [{'id': 7, 'corners': corners.tolist()}]}
    try:
        hub._project_axes('front', telemetry)
        origin, right, up, out = telemetry['tags'][0]['axes']
        assert right[0] > origin[0]
        assert up[1] < origin[1]
        assert len(out) == 2
    finally:
        hub.close()


def test_dashboard_distinguishes_saved_provisional_invalid_and_active_calibration(tmp_path):
    hub = stream.StreamHub(['front'])
    service = dashboard_service(tmp_path)
    hub.attach_service(service)
    destination = service.config.cameras[0].calibration
    try:
        camera = json.loads(hub.dashboard_status())['cameras'][0]
        assert camera['calibration'] == 'missing'
        saved = {'camera_id': 'front', 'width': 640, 'height': 360, 'pixel_format': 'MJPEG',
                 'camera_matrix': [[500, 0, 320], [0, 500, 180], [0, 0, 1]],
                 'distortion_coefficients': [0, 0, 0, 0, 0]}
        destination.write_text(json.dumps(saved))
        camera = json.loads(hub.dashboard_status())['cameras'][0]
        assert camera['calibration'] == 'calibrated' and not camera['restart_required']
        saved['provisional'] = True
        destination.write_text(json.dumps(saved))
        camera = json.loads(hub.dashboard_status())['cameras'][0]
        assert camera['calibration'] == 'provisional' and camera['restart_required']
        saved['width'] = 800
        destination.write_text(json.dumps(saved))
        camera = json.loads(hub.dashboard_status())['cameras'][0]
        assert camera['calibration'] == 'invalid' and 'mismatch' in camera['calibration_error']
        assert camera['active_calibration'] == 'calibrated'
        assert camera['telemetry'] == {}
    finally:
        hub.close()


def test_dashboard_routing_and_inspection_metadata_match_the_encoded_frame(tmp_path):
    import base64
    hub = stream.StreamHub(['front'])
    hub.attach_service(dashboard_service(tmp_path))
    server = hub.serve('127.0.0.1', 0)
    base = f'http://127.0.0.1:{server.server_address[1]}'
    result = []
    def read():
        with urllib.request.urlopen(base + '/inspection/front?after=0', timeout=3) as response:
            result.append(json.load(response))
    try:
        with urllib.request.urlopen(base + '/', timeout=2) as response:
            assert b'Vision dashboard' in response.read()
        reader = threading.Thread(target=read)
        reader.start()
        deadline = time.monotonic() + 1
        while hub.cameras['front'].clients == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        with hub.cameras['front'].condition:
            hub.cameras['front'].telemetry = {'sequence': 42, 'tags': [{'id': 7}]}
        hub.publish('front', np.zeros((8, 16), np.uint8), 42)
        reader.join(3)
        assert result[0]['sequence'] == result[0]['telemetry']['sequence'] == 42
        assert base64.b64decode(result[0]['jpeg']).startswith(b'\xff\xd8')
        assert result[0]['telemetry']['tags'][0]['id'] == 7
    finally:
        hub.close()


def test_dashboard_exports_field_tag_orientation(tmp_path):
    from spot_vision.pose import FieldLayout, quaternion_to_matrix
    service = dashboard_service(tmp_path)
    service.layout = FieldLayout.load(Path(__file__).resolve().parents[2] /
                                      'config/2026-rebuilt-welded.json')
    hub = stream.StreamHub(['front'])
    hub.attach_service(service)
    try:
        data = json.loads(hub.dashboard_status())
        assert len(data['field_tags']) == 32
        for tag in data['field_tags']:
            transform = service.layout.tags[tag['id']].field_from_tag
            np.testing.assert_allclose(tag['translation'], transform[:3, 3])
            np.testing.assert_allclose(quaternion_to_matrix(tag['quaternion']),
                                       transform[:3, :3], atol=1e-12)
    finally:
        hub.close()


def test_camera_controls_http_validates_token_camera_payload_and_driver_errors(tmp_path):
    from types import SimpleNamespace
    from spot_vision.camera_controls import ControlError

    class Controls:
        def read(self):
            return [{'name': 'brightness', 'value': 0}]

        def set(self, name, value):
            if name != 'brightness' or type(value) is not int or not -64 <= value <= 64:
                raise ValueError('Invalid control value')
            if value == 42:
                raise ControlError('Device disconnected')
            return [{'name': name, 'value': value}]

    hub = stream.StreamHub(['front'])
    service = dashboard_service(tmp_path)
    service.capture_workers = [SimpleNamespace(camera=service.config.cameras[0], controls=Controls())]
    hub.attach_service(service)
    server = hub.serve('127.0.0.1', 0)
    url = f'http://127.0.0.1:{server.server_address[1]}/api/camera-controls'
    def post(value, token='', camera_id='front'):
        return urllib.request.urlopen(urllib.request.Request(url, method='POST',
            headers={'Content-Type': 'application/json', 'X-Camera-Token': token},
            data=json.dumps({'camera_id': camera_id, 'name': 'brightness', 'value': value}).encode()), timeout=2)
    try:
        with urllib.request.urlopen(url+'?id=front', timeout=2) as response:
            data = json.load(response)
        assert data['controls'][0]['value'] == 0
        for value, token, camera_id, expected in [
            (10, '', 'front', 403), (10, data['token'], 'unknown', 404),
            (65, data['token'], 'front', 400), (42, data['token'], 'front', 503),
        ]:
            with pytest.raises(urllib.error.HTTPError) as error:
                post(value, token, camera_id)
            assert error.value.code == expected
        with post(-12, data['token']) as response:
            assert json.load(response)['controls'][0]['value'] == -12
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(url, data=b'[]', method='POST'), timeout=2)
        assert error.value.code == 400
    finally:
        hub.close()
