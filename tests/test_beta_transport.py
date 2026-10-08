"""Local NT4 integration. This is not roboRIO clock qualification."""

import socket
import time
from pathlib import Path

import numpy as np
import pytest
from beta_fixtures import manifest

from spot_vision.beta_transport import BetaNtTransport, make_observation
from spot_vision.clock import nt_now_us
from spot_vision.config import NtConfig
from spot_vision.configuration import ConfigurationService
from spot_vision.models import DetectedFrame, DetectionBatch, FramePacket, PoseSolution
from spot_vision.persistence import StateStore
from spot_vision.proto import vision_v2_pb2 as wire


@pytest.fixture
def link(tmp_path):
    ntcore = pytest.importorskip("ntcore")
    server = ntcore.NetworkTableInstance.create()
    client = ntcore.NetworkTableInstance.create()
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
    except PermissionError:
        ntcore.NetworkTableInstance.destroy(server)
        ntcore.NetworkTableInstance.destroy(client)
        pytest.skip("local NT server requires socket permission")
    server.startServer("", "127.0.0.1", 0, port)
    applied = []
    configuration = ConfigurationService(
        StateStore(tmp_path), lambda state, _: applied.append(state)
    )
    camera = wire.CameraGeneration(
        camera_name="front",
        binding_id="usb-a",
        binding_generation=1,
        mode_id="640x480",
        optical_signature="fixed-lens-1",
    )
    transport = BetaNtTransport(
        NtConfig(server="127.0.0.1"), configuration, lambda: [camera], instance=client
    )
    profile = server.getRawTopic("/Spot/v2/robot/manifest").publish(
        "proto:spot.vision.v2.Manifest",
        ntcore.PubSubOptions(keepDuplicates=True, sendAll=True, periodic=0.005),
    )
    state = server.getRawTopic("/Spot/v2/robot/state").publish(
        "proto:spot.vision.v2.RobotState",
        ntcore.PubSubOptions(keepDuplicates=True, sendAll=True, periodic=0.005),
    )
    observation = server.getRawTopic("/Spot/v2/front/observations").subscribe(
        "proto:spot.vision.v2.Observation", b"", ntcore.PubSubOptions(sendAll=True, pollStorage=32)
    )
    client.setServer("127.0.0.1", port)
    yield server, client, transport, configuration, applied, profile, state, observation
    transport.close()
    profile.close()
    state.close()
    observation.close()
    client.stopClient()
    server.stopServer()
    ntcore.NetworkTableInstance.destroy(client)
    ntcore.NetworkTableInstance.destroy(server)


def wait_for(predicate, step=lambda: None, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        step()
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "NT condition did not converge"


def handshake(link):
    _, client, transport, config, _, publisher, state, _ = link
    client.startClient4("spot-beta-test")

    def step():
        publisher.set(manifest().SerializeToString())
        state.set(wire.RobotState(robot_session="robot-1", sequence=1).SerializeToString())
        transport.poll()

    wait_for(lambda: config.fresh and transport._ack is not None, step)


def test_nt_exchange_handshake_withhold_and_no_tag_server_timestamp(link):
    _server, client, transport, _config, applied, _, _, subscriber = link
    before_ns = time.monotonic_ns()
    assert transport.context("front", before_ns, None) is None
    handshake(link)
    assert applied and transport.clock.snapshot().state == "Synchronized"
    assert transport.context("front", before_ns, None) is None
    captured_ns = time.monotonic_ns()
    context = transport.context("front", captured_ns, None)
    assert context is not None
    frame = FramePacket(
        "front",
        1,
        1,
        nt_now_us(),
        captured_ns,
        np.zeros((480, 640, 2), dtype=np.uint8),
        capture_epoch="capture-1",
    )
    detected = DetectedFrame(frame, DetectionBatch((), 0), 0)
    message = make_observation(detected, PoseSolution(), context, 1)
    assert not message.candidates and transport.publish(message, captured_ns)
    wait_for(lambda: bool(subscriber.get()))
    packet = subscriber.getAtomic()
    decoded = wire.Observation.FromString(packet.value)
    assert decoded.sequence == 1 and not decoded.candidates
    expected = frame.capture_timestamp_us + client.getServerTimeOffset()
    assert packet.time == expected
    # The server-local stamp and explicit server stamp agree for a remote value.
    assert packet.serverTime in (0, 1, expected)


def test_disconnect_expiry_and_reconnect_require_new_ack_and_new_frames(link):
    _, client, transport, config, _, _publisher, _, _ = link
    handshake(link)
    first = transport._ack
    capture_before = time.monotonic_ns()
    client.stopClient()
    wait_for(lambda: not config.connected)
    assert transport.context("front", time.monotonic_ns(), 0.003) is None
    assert not config.standalone
    handshake(link)
    second = transport._ack
    assert second.connection_epoch > first.connection_epoch
    assert second.sync_epoch > first.sync_epoch
    assert transport.context("front", capture_before, 0.003) is None
    wait_for(lambda: transport.context("front", time.monotonic_ns(), 0.003) is not None)
    transport.clock.snapshot(time.monotonic_ns() + 31_000_000_000)
    assert transport.context("front", time.monotonic_ns(), 0.003) is None


def test_robot_state_listener_can_lock_configuration_independently_of_apply(link):
    _, _, _transport, config, _, _, publisher, _ = link
    handshake(link)
    publisher.set(
        wire.RobotState(robot_session="robot-1", enabled=True, sequence=2).SerializeToString()
    )
    wait_for(lambda: config._robot_state is not None and config._robot_state.enabled)
    with pytest.raises(ValueError, match="locked"):
        config.require_eligible()


def test_golden_python_packets_round_trip_and_match_hashes():
    from spot_vision.beta_contract import content_hash, validate_observation

    root = Path(__file__).parent / "data/beta"
    golden = wire.Manifest.FromString((root / "manifest.bin").read_bytes())
    assert golden.manifest_hash == content_hash(golden.profile)
    for name in ("empty", "multi", "ippe", "ambiguous"):
        data = (root / f"{name}.bin").read_bytes()
        message = wire.Observation.FromString(data)
        validate_observation(message)
        assert message.SerializeToString(deterministic=True) == data


def test_robot_decision_diagnostics_are_bounded_current_and_cleared_on_apply(link):
    import json

    import ntcore

    server, _, transport, config, *_ = link
    handshake(link)
    publisher = server.getStringTopic("/Spot/v2/robot/decisions").publish(
        ntcore.PubSubOptions(periodic=0.005, sendAll=True)
    )
    try:
        sync = transport.clock.snapshot()
        decision = {
            "state": "ACCEPTED",
            "fused": False,
            "capture_epoch": "current-camera",
            "sequence": 1,
            "capture_fpga_s": (nt_now_us() + sync.offset_us) / 1e6,
            "service_session": transport.session,
            "runtime_generation": config.acknowledged_generation,
            "connection_epoch": sync.connection_epoch,
            "sync_epoch": sync.sync_epoch,
            "ignored_nonfinite": float("inf"),
        }

        def publish():
            publisher.set(
                json.dumps(
                    {
                        "robot_session": "robot-1",
                        "manifest_hash": config.manifest.manifest_hash,
                        "fusion_enabled": False,
                        "cameras": {"front": decision},
                    }
                )
            )
            transport.poll()

        wait_for(lambda: bool(transport.robot_decisions), publish)
        observed = transport.robot_decisions["front"]
        assert not observed["fusion_enabled"] and not observed["fused"]
        assert "ignored_nonfinite" not in observed
        # Malformed diagnostic JSON cannot break later polling/HTTP JSON.
        publisher.set("[]")
        wait_for(lambda: not transport._decisions.readQueue(), transport.poll, seconds=0.1)
        transport.invalidate_configuration()
        assert transport.robot_decisions == {}
    finally:
        publisher.close()
