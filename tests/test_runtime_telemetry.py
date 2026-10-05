"""Optional system integrations must stay usable with missing or malformed inputs."""
import json
import logging
import math
import sys
from types import SimpleNamespace

import pytest

from spot_vision import clock, health
from spot_vision.logging_utils import JsonFormatter


@pytest.mark.parametrize("readings,expected", [(["42500", "51000"], 51.),
                                              (["42.5", "48"], 48.),
                                              (["bad", "37000"], 37.)])
def test_temperature_takes_hottest_readable_sensor(monkeypatch, readings, expected):
    monkeypatch.setattr(health.glob, "glob", lambda _: list(range(len(readings))))
    monkeypatch.setattr(health, "Path", lambda index: SimpleNamespace(read_text=lambda: readings[index]))
    assert health.jetson_temperature_c() == expected


def test_absent_temperature_is_explicitly_unknown(monkeypatch):
    monkeypatch.setattr(health.glob, "glob", lambda _: [])
    assert math.isnan(health.jetson_temperature_c())


def test_watchdog_emits_systemd_ready_ping_and_stopping(monkeypatch):
    messages = []
    notifier = SimpleNamespace(notify=messages.append)
    monkeypatch.setitem(sys.modules, "sdnotify", SimpleNamespace(SystemdNotifier=lambda: notifier))
    watchdog = health.Watchdog()
    watchdog.ready()
    watchdog.ping("four cameras running")
    watchdog.stopping()
    assert messages == ["READY=1", "WATCHDOG=1\nSTATUS=four cameras running", "STOPPING=1"]


def test_watchdog_without_sdnotify_is_noop(monkeypatch):
    monkeypatch.setitem(sys.modules, "sdnotify", None)
    watchdog = health.Watchdog()
    watchdog.ready()
    watchdog.ping()
    watchdog.stopping()


@pytest.mark.parametrize("ntcore", [None, SimpleNamespace()])
def test_nt_clock_falls_back_to_monotonic_microseconds(monkeypatch, ntcore):
    monkeypatch.setitem(sys.modules, "ntcore", ntcore)
    monkeypatch.setattr(clock.time, "monotonic_ns", lambda: 123456789)
    assert clock.nt_now_us() == 123456


def test_nt_clock_prefers_synchronized_time(monkeypatch):
    monkeypatch.setitem(sys.modules, "ntcore", SimpleNamespace(_now=lambda: 98765))
    assert clock.nt_now_us() == 98765


def test_json_log_includes_exception_and_interpolated_message():
    try:
        raise RuntimeError("capture failed")
    except RuntimeError:
        record = logging.LogRecord("spot", logging.ERROR, __file__, 1,
                                   "camera %s", ("4",), sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "camera 4"
    assert "RuntimeError: capture failed" in payload["exception"]
    assert "prototype" not in payload
