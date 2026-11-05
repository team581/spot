"""Exercise the packaged startup path without starting USB, NT, or network workers."""

import http.client
import json
import signal
from types import SimpleNamespace
from unittest.mock import Mock

from spot_vision import app, cli


def test_service_starts_with_the_built_dashboard(tmp_path, monkeypatch):
    installation = tmp_path / "installation.json"
    installation.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "backend": "cpu",
                "nt": {"enabled": False},
                "http": {"bind": "127.0.0.1", "port": 0},
            }
        )
    )
    handlers, servers = {}, []
    http_server = app.HttpServer

    def create_server(*args, **kwargs):
        server = http_server(*args, **kwargs)
        servers.append(server)
        return server

    def ready():
        connection = http.client.HTTPConnection("127.0.0.1", servers[0].server_port, timeout=3)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            assert response.status == 200
            assert b"/assets/" in response.read()
        finally:
            connection.close()
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    runtime = SimpleNamespace(
        start=Mock(), close=Mock(), watchdog=SimpleNamespace(ready=ready), endpoint={}
    )
    network = SimpleNamespace(worker=SimpleNamespace(start=Mock()), close=Mock())
    monkeypatch.setattr(app, "local_addresses", lambda: ["127.0.0.1"])
    monkeypatch.setattr(app, "software_info", lambda: {})
    monkeypatch.setattr(app, "Runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(app, "CalibrationManager", lambda runtime: None)
    monkeypatch.setattr(app, "NetworkClient", lambda: network)
    monkeypatch.setattr(app, "HttpServer", create_server)
    monkeypatch.setattr(
        app.signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler)
    )
    assert (
        cli.main(["run", "--installation", str(installation), "--state-root", str(tmp_path)]) == 0
    )
    runtime.start.assert_called_once()
    runtime.close.assert_called_once()
    network.close.assert_called_once()
