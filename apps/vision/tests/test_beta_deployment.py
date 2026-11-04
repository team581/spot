"""Activation transaction tests use temporary releases and simulated service responses."""

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", [None, "identity", "stalled"])
def test_activation_verifies_running_process_and_restores_previous_on_failure(
    tmp_path, monkeypatch, failure
):
    spec = importlib.util.spec_from_file_location(
        "beta_activate", Path(__file__).parents[1] / "deploy/activate.py"
    )
    activate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(activate)
    root, state = tmp_path / "installed", tmp_path / "state"
    state.mkdir()
    old_id, new_id = "a" * 16, "b" * 16
    old, new = root / "releases" / old_id, root / "releases" / new_id
    old.mkdir(parents=True)
    (new / ".venv/bin").mkdir(parents=True)
    (new / ".venv/bin/spot-vision").touch()
    (root / "current").symlink_to(old)
    saved_state = b"committed camera state"
    (state / "active.json").write_bytes(saved_state)
    prior = {"release_id": old_id, "verification": "verified setup; hardware pending"}
    (state / "deployments.json").write_text(json.dumps({"last_successful_deployment": prior}))
    activate.ROOT, activate.STATE = root, state
    monkeypatch.setattr(activate.os, "geteuid", lambda: 0)
    monkeypatch.setattr(activate, "stamp", lambda: None)
    args = ["activate.py", new_id, "--timeout", "1"]
    if failure != "stalled":
        args.append("--setup-only")
    monkeypatch.setattr(sys, "argv", args)
    read_bytes = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda path: (
            b'{"http":{"port":5800}}'
            if str(path) == "/etc/spot-vision/beta.json"
            else read_bytes(path)
        ),
    )
    monkeypatch.setattr(
        activate.subprocess,
        "check_output",
        lambda *a, **k: json.dumps({"release_id": new_id, "native_sha256": "new-native"}).encode(),
    )
    restarts = []
    monkeypatch.setattr(activate.subprocess, "run", lambda args, **kwargs: restarts.append(args))
    clock = [0]

    def now():
        clock[0] += 0.15
        return clock[0]

    monkeypatch.setattr(activate.time, "monotonic", now)
    monkeypatch.setattr(activate.time, "sleep", lambda _: None)

    def urlopen(url, timeout):
        current = (root / "current").resolve().name
        if url.endswith("/health"):
            status = {
                "release": {
                    "release_id": current,
                    "native_sha256": "wrong"
                    if failure == "identity" and current == new_id
                    else "new-native",
                },
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
                        "metrics": {"detect_age_s": 1.5},
                    }
                ],
            }
            return io.BytesIO(json.dumps(status).encode())
        return io.BytesIO(b"<!doctype html><title>Spot</title>")

    monkeypatch.setattr(activate, "urlopen", urlopen)
    result = activate.main()
    recorded = json.loads((state / "deployments.json").read_text())
    assert (state / "active.json").read_bytes() == saved_state
    assert not (root / "current.next").exists()
    if failure:
        assert result == 1 and (root / "current").resolve() == old
        assert recorded["rollback"] is True
        assert recorded["latest_attempt"]["restored_release"] == old_id
        assert recorded["last_successful_deployment"] == prior
        assert len(restarts) == 2
    else:
        assert result == 0 and (root / "current").resolve() == new
        assert recorded["rollback"] is False
        assert recorded["last_successful_deployment"]["release_id"] == new_id
        assert len(restarts) == 1
