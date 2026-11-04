"""Alpha startup failures must close preview and calibration resources."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", [None, "viewer", "service"])
def test_alpha_daemon_cleanup_and_shared_camera_observers(monkeypatch, failure):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "tested_prototype_daemon", ROOT / "prototype_daemon.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events = []
    config = SimpleNamespace(
        cameras=[SimpleNamespace(id="1", enabled=True), SimpleNamespace(id="off", enabled=False)]
    )

    class Hub:
        def __init__(self, ids):
            assert ids == ["1"]

        def latest_frame(self, camera_id):
            return camera_id

        def publish_result(self, *_):
            pass

        def publish_capture(self, *_):
            pass

        def attach_calibration(self, calibration):
            events.append("attach calibration")

        def attach_service(self, service):
            events.append("attach service")

        def serve(self, host, port):
            assert host == "127.0.0.1" and port == 8765
            if failure == "viewer":
                raise OSError("port in use")

        def close(self):
            events.append("hub closed")

    class Calibration:
        def __init__(self, supplied, source, root, html):
            assert supplied is config and source("1") == "1"

        def close(self):
            events.append("calibration closed")

    class Service:
        def __init__(self, supplied, *, result_observer, capture_observer):
            assert supplied is config
            assert result_observer.__self__ is capture_observer.__self__
            events.append("service created")

        def run_forever(self):
            if failure == "service":
                raise RuntimeError("initialization failed")
            events.append("ran")

    monkeypatch.setattr(module, "load_config", lambda _: config)
    monkeypatch.setattr(module, "configure_logging", lambda **_: None)
    monkeypatch.setattr(module, "StreamHub", Hub)
    monkeypatch.setattr(module, "AlphaCalibration", Calibration)
    monkeypatch.setattr(module, "VisionService", Service)
    args = ["--config", "config.json", "--host", "127.0.0.1"]
    if failure == "service":
        with pytest.raises(RuntimeError, match="initialization failed"):
            module.main(args)
    else:
        assert module.main(args) == 0
        assert "ran" in events
    assert events[-2:] == ["calibration closed", "hub closed"]
