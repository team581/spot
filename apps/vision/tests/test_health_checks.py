"""Deployment qualification rejects stale/mismatched processes and unready robots."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from spot_vision import cli
from spot_vision.config import ConfigError

PACKAGE = "/nix/store/test-spot-vision"


@pytest.fixture
def ready():
    return {
        "software": {"package_path": PACKAGE},
        "fresh": True,
        "clock": {"state": "Synchronized"},
        "applied_generation": "current",
        "revision": "current",
        "lock_reason": "",
        "cameras": [
            {
                "required": True,
                "connected": True,
                "calibrated": True,
                "timestamp_qualified": True,
                "metrics": {"detect_age_s": 0.1},
            }
        ],
    }


def test_ready_robot_passes(ready):
    cli._check_health_status(ready, PACKAGE, robot=True)


def test_health_rejects_a_different_running_package(ready):
    ready["software"]["package_path"] = "/nix/store/old-spot-vision"
    with pytest.raises(ConfigError, match="different package"):
        cli._check_health_status(ready, PACKAGE, robot=False)


@pytest.mark.parametrize(
    "fault",
    [
        "stale",
        "clock",
        "profile",
        "enabled",
        "no cameras",
        "disconnected",
        "uncalibrated",
        "unqualified",
        "slow",
        "no detections",
    ],
)
def test_robot_qualification_requires_all_readiness_checks(ready, fault):
    camera = ready["cameras"][0]
    if fault == "stale":
        ready["fresh"] = False
    elif fault == "clock":
        ready["clock"]["state"] = "Unsynchronized"
    elif fault == "profile":
        ready["applied_generation"] = "old"
    elif fault == "enabled":
        ready["lock_reason"] = "Robot is enabled"
    elif fault == "no cameras":
        ready["cameras"] = []
    elif fault == "disconnected":
        camera["connected"] = False
    elif fault == "uncalibrated":
        camera["calibrated"] = False
    elif fault == "unqualified":
        camera["timestamp_qualified"] = False
    elif fault == "slow":
        camera["metrics"]["detect_age_s"] = 1.5
    elif fault == "no detections":
        camera["metrics"]["detect_age_s"] = None
    with pytest.raises(ConfigError):
        cli._check_health_status(ready, PACKAGE, robot=True)
    cli._check_health_status(ready, PACKAGE, robot=False)


def test_health_cli_waits_for_the_selected_package(ready, monkeypatch):
    requests = []
    expected = str(Path(sys.prefix).resolve())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            status = {
                **ready,
                "software": {
                    "package_path": PACKAGE if len(requests) == 1 else expected,
                },
            }
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    try:
        assert (
            cli.main(
                [
                    "check-health",
                    "--robot",
                    "--timeout",
                    "2",
                    "--url",
                    f"http://127.0.0.1:{server.server_port}",
                ]
            )
            == 0
        )
        assert requests == ["/health", "/health"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
