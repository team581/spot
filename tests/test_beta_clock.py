from spot_vision.clock import ClockGate


def test_connection_and_actual_exchange_required_and_absolute_offset_is_unrestricted():
    clock = ClockGate()
    clock.update(900_000_000, 100, True, 100)
    assert clock.snapshot(100).state == "Waiting"
    clock.connection("robot-1")
    assert clock.snapshot(100).state == "Waiting"
    clock.update(900_000_000, 100, True, 200)
    ready = clock.snapshot(200)
    assert ready.state == "Synchronized" and ready.ready_since_ns == 200
    clock.connection(None)
    assert clock.snapshot(300).state == "Waiting"
    clock.connection("robot-2")
    clock.update(-20_000_000, 100, True, 400)
    reboot = clock.snapshot(400)
    assert reboot.state == "Synchronized"
    assert reboot.connection_epoch > ready.connection_epoch and reboot.sync_epoch > ready.sync_epoch


def test_expiry_jump_and_high_rtt_invalidate_old_frames():
    clock = ClockGate(expiry_s=3)
    clock.connection("robot")
    clock.update(500, 100, True, 1_000_000_000)
    epoch = clock.snapshot(1_000_000_000).sync_epoch
    assert clock.snapshot(4_000_000_001).state == "Waiting"
    clock.update(500, 100, True, 5_000_000_000)
    assert clock.snapshot(5_000_000_000).sync_epoch > epoch
    clock.update(6_000, 100, True, 6_000_000_000)
    invalid = clock.snapshot(6_000_000_000)
    assert invalid.state == "Invalid" and invalid.discontinuities == 1
    clock.update(6_000, 100, True, 7_000_000_000)
    assert clock.snapshot(7_000_000_000).ready_since_ns == 7_000_000_000
    clock.update(6_000, 5_001, True, 8_000_000_000)
    assert clock.snapshot(8_000_000_000).state == "Invalid"
