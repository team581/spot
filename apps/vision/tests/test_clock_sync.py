from types import SimpleNamespace

from spot_vision.clock import NtClock


def test_sync_requires_connection_and_ntcore_offset():
    connected, offset = False, None
    clock = NtClock(
        SimpleNamespace(isConnected=lambda: connected, getServerTimeOffset=lambda: offset)
    )
    assert clock.snapshot().state == "Waiting"
    offset = 900_000_000
    assert clock.snapshot().offset_us is None
    connected = True
    assert clock.snapshot().state == "Synchronized"
    assert clock.snapshot().offset_us == offset
    offset = None
    assert clock.snapshot().state == "Waiting"


def test_offset_has_no_custom_expiry_or_reconnect_timer(monkeypatch):
    from spot_vision import clock as module

    clock = NtClock(
        SimpleNamespace(isConnected=lambda: True, getServerTimeOffset=lambda: -20000000)
    )
    before = clock.snapshot()
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 10**18)
    assert clock.snapshot() == before
