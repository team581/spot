from __future__ import annotations

import http.client
import json
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from spot_vision.http_server import HttpServer


@pytest.fixture
def web(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Spot</title>")
    submissions = []

    def submit(operation, payload):
        submissions.append((operation, payload, threading.current_thread().name))
        future = Future()
        future.set_result({"revision": "new", "applied_generation": "new"})
        return future

    runtime = SimpleNamespace(submit=submit, status=lambda: {"revision": "old", "cameras": []})
    server = HttpServer(("127.0.0.1", 0), runtime, assets=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = f"127.0.0.1:{server.server_port}"

    def request(method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    status, headers, raw = request("GET", "/api/session")
    assert status == 200
    session = json.loads(raw)
    session_headers = {
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-Spot-CSRF": session["csrf"],
        "Origin": "http://" + host,
        "Content-Type": "application/json",
    }
    yield request, session_headers, submissions, server
    server.shutdown()
    server.server_close()
    thread.join(2)


def operation(**changes):
    return json.dumps(
        {
            "operation": "tune",
            "payload": {"name": "front", "values": {"gain": 2}, "revision": "old"},
            "request_id": "request_123",
            **changes,
        }
    )


def test_session_csrf_same_origin_and_host_are_required(web):
    request, headers, submissions, _ = web
    for bad in (
        {},
        {**headers, "Origin": "http://evil.invalid"},
        {**headers, "X-Spot-CSRF": "wrong"},
        {**headers, "Host": "evil.invalid:80"},
    ):
        assert request("POST", "/api/operations", operation(), bad)[0] == 403
    assert submissions == []


def test_direct_address_works_when_interface_was_absent_at_startup(web):
    request, _, _, server = web
    # Model a wildcard listener started before its interface address existed.
    server.allowed_hosts.discard("127.0.0.1")
    port = server.server_port
    assert request("GET", "/api/status", headers={"Host": f"127.0.0.1:{port}"})[0] == 200
    for hostname in ("evil.invalid", "192.0.2.1"):
        assert request("GET", "/api/status", headers={"Host": f"{hostname}:{port}"})[0] == 403


def test_structured_bounded_requests_reject_unknown_fields_and_nan(web):
    request, headers, submissions, _ = web
    invalid = [
        operation(operation="shell"),
        operation(payload={"name": "front", "revision": "old", "path": "/etc/passwd"}),
        operation(payload={"name": "front", "revision": "old", "values": {"gain": float("nan")}}),
        operation(request_id="x"),
        "{}",
        "[" * 10,
    ]
    for body in invalid:
        assert request("POST", "/api/operations", body, headers)[0] == 400
    assert request("POST", "/api/operations", "x" * 65537, headers)[0] == 400
    assert submissions == []


def test_handlers_enqueue_once_and_acknowledge_only_completed_job(web):
    request, headers, submissions, _ = web
    first = request("POST", "/api/operations", operation(), headers)
    second = request("POST", "/api/operations", operation(), headers)
    assert first[0] == second[0] == 202
    job = json.loads(first[2])["job_id"]
    assert job == json.loads(second[2])["job_id"]
    assert len(submissions) == 1
    assert submissions[0][:2] == (
        "tune",
        {"name": "front", "values": {"gain": 2}, "revision": "old"},
    )
    response = json.loads(request("GET", "/api/jobs/" + job, headers=headers)[2])
    assert response["state"] == "applied" and response["applied_generation"] == "new"
    assert request("GET", "/api/jobs/" + job)[0] == 404


def test_live_control_rate_and_asset_paths_are_bounded(web):
    request, headers, submissions, _ = web
    for i in range(2):
        assert (
            request("POST", "/api/operations", operation(request_id=f"request_{i:03}"), headers)[0]
            == 202
        )
    assert (
        request("POST", "/api/operations", operation(request_id="request_more"), headers)[0] == 400
    )
    assert len(submissions) == 2
    assert request("GET", "/../http_server.py")[0] == 404
    assert request("GET", "/%2e%2e/%2e%2e/etc/passwd")[0] == 404
    response = request("GET", "/")
    assert response[0] == 200 and "default-src" in response[1]["Content-Security-Policy"]


def test_preview_allows_twenty_fps_but_rejects_request_bursts(web, monkeypatch):
    from spot_vision import http_server

    request, headers, _, server = web
    now = [time.monotonic()]
    monkeypatch.setattr(http_server, "time", SimpleNamespace(monotonic=lambda: now[0]))
    server.runtime.frames = SimpleNamespace(preview=lambda *args: {"sequence": 1})
    path = "/api/frame/" + "a" * 64
    assert request("GET", path, headers=headers)[0] == 200
    now[0] += 0.05
    assert request("GET", path, headers=headers)[0] == 200
    now[0] += 0.001
    assert request("GET", path, headers=headers)[0] == 429


def test_pending_rejected_job(web):
    request, headers, _, server = web
    pending = Future()
    server.runtime.submit = lambda operation, payload: pending
    status, _, raw = request("POST", "/api/operations", operation(), headers)
    assert status == 202
    path = "/api/jobs/" + json.loads(raw)["job_id"]
    assert json.loads(request("GET", path, headers=headers)[2]) == {"state": "pending"}
    pending.set_exception(ValueError("Camera readback rejected the requested gain"))
    result = json.loads(request("GET", path, headers=headers)[2])
    assert result == {"state": "rejected", "error": "Camera readback rejected the requested gain"}


def test_docs_directory_pages_assets_and_missing_paths(web):
    request, _, submissions, server = web
    docs = server.assets / "docs"
    article = docs / "operator/calibrate"
    article.mkdir(parents=True)
    (docs / "index.html").write_text("<!doctype html><title>Operator guide</title>")
    page = b"<!doctype html><title>Calibrate</title>"
    (article / "index.html").write_bytes(page)
    (docs / "search.wasm").write_bytes(b"\x00asm")

    for path in ("/docs", "/docs/operator/calibrate"):
        status, headers, body = request("GET", path)
        assert status == 301 and headers["Location"] == path + "/" and body == b""
    status, headers, body = request("GET", "/docs/operator/calibrate/")
    assert status == 200 and headers["Content-Type"] == "text/html" and body == page
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
    request, _, _, server = web
    outside = tmp_path.parent / (tmp_path.name + "-private")
    outside.mkdir()
    (outside / "index.html").write_text("private")
    (server.assets / "docs").symlink_to(outside, target_is_directory=True)
    assert request("GET", "/docs/")[0] == 404


def test_two_browser_sessions_cannot_overwrite_an_acknowledged_revision(web, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from robot_fixtures import manifest
    from spot_vision import protocol_models as wire
    from spot_vision.configuration import ConfigurationService
    from spot_vision.persistence import StateStore

    request, first_headers, _, server = web
    config = ConfigurationService(StateStore(tmp_path / "state"), lambda *_: None)
    config.connection_changed(True)
    config.accept_manifest(manifest())
    config.robot_state(wire.RobotState(robot_session="robot-1", enabled=False, sequence=1))
    original = config.state.generation
    _, headers, raw = request("GET", "/api/session")
    second_headers = {
        **first_headers,
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-Spot-CSRF": json.loads(raw)["csrf"],
    }

    def apply(operation, payload):
        result = config.tune(payload["name"], payload["values"], payload["revision"])
        return {"revision": result.generation, "applied_generation": result.generation}

    with ThreadPoolExecutor(max_workers=1) as queue:
        server.runtime.submit = lambda operation, payload: queue.submit(apply, operation, payload)
        jobs = []
        for i, client in enumerate((first_headers, second_headers)):
            body = operation(
                request_id=f"concurrent_{i}",
                payload={"name": "front", "values": {"gain": 3 + i}, "revision": original},
            )
            status, _, raw = request("POST", "/api/operations", body, client)
            assert status == 202
            jobs.append((json.loads(raw)["job_id"], client))
    results = [
        json.loads(request("GET", "/api/jobs/" + job, headers=client)[2]) for job, client in jobs
    ]
    assert results[0]["state"] == "applied"
    assert results[1]["state"] == "rejected" and "revision conflict" in results[1]["error"]
    assert config.effective_controls("front")["gain"] == 3
    assert request("GET", "/api/jobs/" + jobs[0][0], headers=second_headers)[0] == 404


def test_network_changes_use_existing_session_guards_and_strict_payloads(web):
    request, headers, submissions, server = web
    body = operation(
        operation="network/apply",
        payload={"interface": "eth0", "mode": "static", "address": "10.5.81.11/24"},
    )
    assert request("POST", "/api/operations", body, {})[0] == 403
    assert request("POST", "/api/operations", body, headers)[0] == 202
    assert submissions[-1][0] == "network/apply"
    for payload in (
        {"interface": "eth0", "mode": "static", "address": "10.5.81.255/24"},
        {"interface": "eth0", "mode": "automatic", "address": "10.5.81.11/24"},
    ):
        assert (
            request(
                "POST",
                "/api/operations",
                operation(operation="network/apply", payload=payload),
                headers,
            )[0]
            == 400
        )
    server.runtime.network = SimpleNamespace(snapshot={"hostname": "spot-2.local"})
    assert (
        request("GET", "/api/status", headers={"Host": f"spot-2.local:{server.server_port}"})[0]
        == 200
    )
    assert (
        request("GET", "/api/status", headers={"Host": f"unregistered.local:{server.server_port}"})[
            0
        ]
        == 403
    )


def test_installed_dashboard_and_docs_are_served_from_any_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = HttpServer(("127.0.0.1", 0), SimpleNamespace())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Request every emitted chunk, including lazy pages absent from index.html.
        assets = list((server.assets / "assets").rglob("*"))
        assert any(path.suffix == ".js" for path in assets)
        assert any(path.suffix == ".css" for path in assets)
        assert not list(server.assets.rglob("*.tsx"))
        paths = ["/", "/blazing-bulldogs.svg", "/docs/", "/docs/pagefind/pagefind.js"]
        paths.extend(
            "/" + path.relative_to(server.assets).as_posix() for path in assets if path.is_file()
        )
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
                    assert response.getheader("Content-Type") == "text/css", path
            finally:
                connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
