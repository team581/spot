from __future__ import annotations

import http.client
import json
import struct
import threading
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from spot_vision.http_server import HttpServer, create_app

HOST = "127.0.0.1:5800"
HEADERS = {"Origin": "http://" + HOST, "Content-Type": "application/json"}
TUNE = {"name": "front", "values": {"gain": 2}, "revision": "old"}


@pytest.fixture
def web(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Spot</title>")
    submissions = []

    def submit(operation, payload):
        submissions.append((operation, payload))
        future = Future()
        if operation.startswith("network/"):
            future.set_result({"result": {}})
        else:
            future.set_result({"revision": "new", "applied_generation": "new"})
        return future

    runtime = SimpleNamespace(submit=submit, status=lambda: {"revision": "old", "cameras": []})
    app = create_app(runtime, assets=tmp_path)
    client = TestClient(app, base_url="http://" + HOST, follow_redirects=False)

    def request(method, path, body=None, headers=None):
        if body is not None and not isinstance(body, str):
            body = json.dumps(body)
        response = client.request(method, path, content=body, headers=headers or {})
        return response.status_code, response.headers, response.content

    yield (
        request,
        submissions,
        SimpleNamespace(
            runtime=runtime,
            assets=tmp_path,
            allowed_hosts=app.state.allowed_hosts,
            port=5800,
            client=client,
        ),
    )


def test_mutations_require_same_origin_json_on_an_installed_host(web):
    request, submissions, _ = web
    for bad in (
        {},
        {**HEADERS, "Origin": "http://evil.invalid"},
        {**HEADERS, "Host": "evil.invalid:80"},
    ):
        assert request("POST", "/api/camera/tune", TUNE, bad)[0] == 403
    assert (
        request("POST", "/api/camera/tune", TUNE, {**HEADERS, "Content-Type": "text/plain"})[0]
        == 400
    )
    assert submissions == []


def test_direct_address_works_when_interface_was_absent_at_startup(web):
    request, _, server = web
    # Model a wildcard listener started before its interface address existed.
    server.allowed_hosts.discard("127.0.0.1")
    port = server.port
    assert request("GET", "/api/status", headers={"Host": f"127.0.0.1:{port}"})[0] == 200
    for hostname in ("evil.invalid", "192.0.2.1"):
        assert request("GET", "/api/status", headers={"Host": f"{hostname}:{port}"})[0] == 403


def test_operations_are_strict_and_bounded(web):
    request, submissions, _ = web
    invalid = [
        {**TUNE, "path": "/etc/passwd"},
        {**TUNE, "values": {"gain": float("nan")}},
        {},
        "[" * 10,
        "x" * (256 * 1024 + 1),
    ]
    for body in invalid:
        assert request("POST", "/api/camera/tune", body, HEADERS)[0] == 400
    assert request("POST", "/api/shell", {}, HEADERS)[0] in {404, 405}
    assert submissions == []
    # Only saved-setup imports may exceed the normal body limit.
    large = {"document": {"blob": "x" * (512 * 1024)}, "revision": "old"}
    assert request("POST", "/api/configuration/apply", large, HEADERS)[0] == 400
    assert request("POST", "/api/configuration/import", large, HEADERS)[0] == 200
    assert [operation for operation, _ in submissions] == ["configuration/import"]


def test_mutation_returns_the_runtime_acknowledgement(web):
    request, submissions, _ = web
    status, _, raw = request("POST", "/api/camera/tune", TUNE, HEADERS)
    assert status == 200
    assert json.loads(raw)["applied_generation"] == "new"
    assert submissions == [("camera/tune", TUNE)]


def test_rejected_and_unacknowledged_mutations(web, monkeypatch):
    from spot_vision import http_server

    request, _, server = web
    rejected = Future()
    rejected.set_exception(ValueError("Camera readback rejected the requested gain"))
    server.runtime.submit = lambda operation, payload: rejected
    status, _, raw = request("POST", "/api/camera/tune", TUNE, HEADERS)
    assert (status, json.loads(raw)) == (
        400,
        {"error": "Camera readback rejected the requested gain"},
    )
    monkeypatch.setattr(http_server, "ACKNOWLEDGEMENT_TIMEOUT_S", 0.01)
    server.runtime.submit = lambda operation, payload: Future()
    assert request("POST", "/api/camera/tune", TUNE, HEADERS)[0] == 504


def test_asset_paths_are_bounded(web):
    request, _, _ = web
    assert request("GET", "/../http_server.py")[0] == 404
    assert request("GET", "/%2e%2e/%2e%2e/etc/passwd")[0] == 404
    response = request("GET", "/")
    assert response[0] == 200 and "default-src" in response[1]["Content-Security-Policy"]


def test_frames_stream_binary_previews_only_to_same_origin_pages(web):
    _, _, server = web
    header = {"capture_epoch": "epoch", "sequence": 1, "processed": True}
    unsubscribed = []
    server.runtime.frames = SimpleNamespace(
        subscribe=lambda identity, notify: lambda: unsubscribed.append(identity),
        frame=lambda identity: (header, b"jpeg"),
    )
    url = f"ws://{HOST}/api/frames/" + "a" * 64
    with server.client.websocket_connect(url, headers={"Origin": "http://" + HOST}) as socket:
        message = socket.receive_bytes()
    (length,) = struct.unpack(">I", message[:4])
    assert json.loads(message[4 : 4 + length]) == header and message[4 + length :] == b"jpeg"
    assert unsubscribed == ["a" * 64]
    for path, headers in (
        (url, {}),
        (url, {"Origin": "http://evil.invalid"}),
        (f"ws://{HOST}/api/frames/front", {"Origin": "http://" + HOST}),
    ):
        with pytest.raises(WebSocketDisconnect):
            with server.client.websocket_connect(path, headers=headers):
                pass


def test_docs_directory_pages_assets_and_missing_paths(web):
    request, submissions, server = web
    docs = server.assets / "docs"
    article = docs / "operator/calibrate"
    article.mkdir(parents=True)
    (docs / "index.html").write_text("<!doctype html><title>Operator guide</title>")
    page = b"<!doctype html><title>Calibrate</title>"
    (article / "index.html").write_bytes(page)
    (docs / "search.wasm").write_bytes(b"\x00asm")

    for path in ("/docs", "/docs/operator/calibrate"):
        status, headers, body = request("GET", path)
        assert status == 307 and headers["Location"].endswith(path + "/") and body == b""
    status, headers, body = request("GET", "/docs/operator/calibrate/")
    assert status == 200 and headers["Content-Type"].startswith("text/html") and body == page
    # The static docs policy permits Starlight and search without changing the dashboard's policy.
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "'wasm-unsafe-eval'" in headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in request("GET", "/")[1]["Content-Security-Policy"]
    assert request("GET", "/docs/")[0] == 200
    assert request("GET", "/docs/search.wasm")[1]["Content-Type"] == "application/wasm"
    assert request("GET", "/docs/missing/")[0] == 404
    assert request("GET", "/docs/operator/calibrate/../../../../secret")[0] == 404
    assert submissions == []


def test_docs_cannot_follow_symlinks_outside_web_assets(web, tmp_path):
    request, _, server = web
    outside = tmp_path.parent / (tmp_path.name + "-private")
    outside.mkdir()
    (outside / "index.html").write_text("private")
    (server.assets / "docs").symlink_to(outside, target_is_directory=True)
    assert request("GET", "/docs/")[0] == 404


def test_concurrent_editors_cannot_overwrite_an_acknowledged_revision(web, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from robot_fixtures import manifest
    from spot_vision.configuration import ConfigurationService
    from spot_vision.persistence import StateStore

    request, _, server = web
    config = ConfigurationService(StateStore(tmp_path / "state"), lambda *_: None)
    config.connection_changed(True)
    config.accept_manifest(manifest())
    original = config.state.generation

    def apply(operation, payload):
        result = config.tune(payload["name"], payload["values"], payload["revision"])
        return {"revision": result.generation, "applied_generation": result.generation}

    with ThreadPoolExecutor(max_workers=1) as queue:
        server.runtime.submit = lambda operation, payload: queue.submit(apply, operation, payload)
        results = [
            request(
                "POST",
                "/api/camera/tune",
                {"name": "front", "values": {"gain": 3 + i}, "revision": original},
                HEADERS,
            )
            for i in range(2)
        ]
    assert results[0][0] == 200
    assert results[1][0] == 400 and b"revision conflict" in results[1][2]
    assert config.effective_controls("front")["gain"] == 3


def test_network_changes_use_strict_payloads_and_hostname_checks(web):
    request, submissions, server = web
    change = {"mode": "static", "address": "10.5.81.11/24"}
    assert request("POST", "/api/network/apply", change, {})[0] == 403
    assert request("POST", "/api/network/apply", change, HEADERS)[0] == 200
    assert submissions[-1] == ("network/apply", change)
    for payload in (
        {"mode": "static", "address": "10.5.81.255/24"},
        {"mode": "automatic", "address": "10.5.81.11/24"},
        {"interface": "spot0", "mode": "static", "address": "10.5.81.11/24"},
    ):
        assert request("POST", "/api/network/apply", payload, HEADERS)[0] == 400
    server.runtime.network = SimpleNamespace(snapshot={"hostname": "spot-2.local"})
    assert request("GET", "/api/status", headers={"Host": f"spot-2.local:{server.port}"})[0] == 200
    assert (
        request("GET", "/api/status", headers={"Host": f"unregistered.local:{server.port}"})[0]
        == 403
    )


def test_installed_dashboard_and_docs_are_served_from_any_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    frames = SimpleNamespace(subscribe=lambda identity, notify: lambda: None, frame=lambda _: None)
    server = HttpServer(("127.0.0.1", 0), SimpleNamespace(frames=frames))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Request every emitted chunk, including lazy pages absent from index.html.
        root = server.app.state.assets
        assets = list((root / "assets").rglob("*"))
        assert any(path.suffix == ".js" for path in assets)
        assert any(path.suffix == ".css" for path in assets)
        assert not list(root.rglob("*.tsx"))
        paths = ["/", "/blazing-bulldogs.svg", "/docs/", "/docs/pagefind/pagefind.js"]
        paths.extend("/" + path.relative_to(root).as_posix() for path in assets if path.is_file())
        for path in paths:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                assert response.status == 200, path
                assert response.read(), path
                if path.endswith(".js"):
                    assert "javascript" in response.getheader("Content-Type"), path
                elif path.endswith(".css"):
                    assert response.getheader("Content-Type").startswith("text/css"), path
            finally:
                connection.close()
        # TestClient bypasses uvicorn, so check the real server can upgrade preview streams.
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            connection.request(
                "GET",
                "/api/frames/" + "a" * 64,
                headers={
                    "Upgrade": "websocket",
                    "Connection": "Upgrade",
                    "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                    "Sec-WebSocket-Version": "13",
                    "Origin": f"http://127.0.0.1:{server.server_port}",
                },
            )
            assert connection.getresponse().status == 101
        finally:
            connection.close()
    finally:
        server.shutdown()
        thread.join(5)


@pytest.mark.parametrize(
    "payload",
    [{"team": t} for t in (0, -1, 25600, True, 9991.0, "9991", None)]
    + [{}, {"team": 9991, "server": "other"}],
)
def test_team_number_request_rejects_invalid_payloads(web, payload):
    request, submissions, _ = web
    assert request("POST", "/api/nt/team", payload, HEADERS)[0] == 400
    assert submissions == []
