from __future__ import annotations

import http.client
import json
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from spot_vision.beta_web import BetaHttpServer


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
    server = BetaHttpServer(("127.0.0.1", 0), runtime, assets=tmp_path)
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
    assert request("GET", "/../beta_web.py")[0] == 404
    assert request("GET", "/%2e%2e/%2e%2e/etc/passwd")[0] == 404
    response = request("GET", "/")
    assert response[0] == 200 and "default-src" in response[1]["Content-Security-Policy"]


def test_preview_allows_twenty_fps_but_rejects_request_bursts(web, monkeypatch):
    from spot_vision import beta_web

    request, headers, _, server = web
    now = [time.monotonic()]
    monkeypatch.setattr(beta_web, "time", SimpleNamespace(monotonic=lambda: now[0]))
    server.runtime.frames = SimpleNamespace(preview=lambda *args: {"sequence": 1})
    path = "/api/frame/" + "a" * 64
    assert request("GET", path, headers=headers)[0] == 200
    now[0] += 0.05
    assert request("GET", path, headers=headers)[0] == 200
    now[0] += 0.001
    assert request("GET", path, headers=headers)[0] == 429


def test_offline_json_asset_and_pending_rejected_job(web):
    request, headers, _, server = web
    docs = b'{"articles":[{"title":"Name a camera"}]}'
    (server.assets / "docs.json").write_bytes(docs)
    status, response_headers, raw = request("GET", "/docs.json")
    assert status == 200 and response_headers["Content-Type"] == "application/json"
    assert raw == docs

    pending = Future()
    server.runtime.submit = lambda operation, payload: pending
    status, _, raw = request("POST", "/api/operations", operation(), headers)
    assert status == 202
    path = "/api/jobs/" + json.loads(raw)["job_id"]
    assert json.loads(request("GET", path, headers=headers)[2]) == {"state": "pending"}
    pending.set_exception(ValueError("Camera readback rejected the requested gain"))
    result = json.loads(request("GET", path, headers=headers)[2])
    assert result == {"state": "rejected", "error": "Camera readback rejected the requested gain"}


def test_two_browser_sessions_cannot_overwrite_an_acknowledged_revision(web, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from beta_fixtures import manifest

    from spot_vision.configuration import ConfigurationService
    from spot_vision.persistence import StateStore
    from spot_vision.proto import vision_v2_pb2 as wire

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
