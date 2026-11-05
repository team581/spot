"""Local NT4 integration of the robot/Spot boundary."""

import socket
import time
from types import SimpleNamespace

import numpy as np
import pytest

from robot_fixtures import RobotPublisher, StatePublisher, manifest
from spot_vision import protocol_models as wire
from spot_vision.clock import nt_now_us
from spot_vision.config import NtConfig
from spot_vision.configuration import ConfigurationService
from spot_vision.models import DetectedFrame, DetectionBatch, FramePacket, PoseSolution
from spot_vision.nt_transport import NtTransport, make_observation
from spot_vision.persistence import StateStore
from spot_vision.structs import FrameResult, RobotDecision, session


def wait(link, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        link.server.flush()
        link.client.flush()
        link.transport.poll()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("NT exchange did not complete")


@pytest.fixture
def link(tmp_path):
    import ntcore

    server, client = ntcore.NetworkTableInstance.create(), ntcore.NetworkTableInstance.create()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server.startServer("", "127.0.0.1", 0, port)
    applied = []
    config = ConfigurationService(StateStore(tmp_path), lambda *args: applied.append(args))
    transport = NtTransport(NtConfig(server="127.0.0.1"), config, lambda _: True, instance=client)
    options = ntcore.PubSubOptions(sendAll=True, keepDuplicates=True, periodic=0.005)
    publisher = RobotPublisher(server, options)
    states = StatePublisher(server, options)
    frames = server.getStructTopic("/Spot/front/observations", FrameResult).subscribe(FrameResult())
    client.setServer("127.0.0.1", port)
    client.startClient4("spot-test")
    result = SimpleNamespace(
        server=server,
        client=client,
        transport=transport,
        config=config,
        publisher=publisher,
        states=states,
        frames=frames,
        applied=applied,
    )
    try:
        wait(result, lambda: config.connected and transport.clock.snapshot().offset_us is not None)
        yield result
    finally:
        transport.close()
        frames.close()
        states.close()
        publisher.close()
        client.stopClient()
        ntcore.NetworkTableInstance.destroy(client)
        ntcore.NetworkTableInstance.destroy(server)


def ready(link):
    message = manifest()
    message.profile.cameras[0].binding_id = "usb-a"
    link.publisher.set(message)
    link.states.set(wire.RobotState(1, [1, 2]))
    wait(link, lambda: link.config.fresh and link.config.tag_selection() is not None)


def observation(link):
    captured = time.monotonic_ns()
    context = link.transport.context("front", captured, 1e-6)
    assert context is not None
    frame = FramePacket(
        "usb-a",
        1,
        nt_now_us(),
        captured,
        np.zeros((4, 4), np.uint8),
        "2" * 32,
        link.config.state.generation,
    )
    message = make_observation(
        DetectedFrame(frame, DetectionBatch((), 0), 0),
        PoseSolution(),
        context,
        1,
        selection=link.config.tag_selection(),
    )
    return message, captured


def test_configuration_waits_for_the_complete_baseline_and_publishes_camera_metadata(link):
    link.publisher.put("cameraConfig", '{"cameras":[],"processing":{}}')
    link.server.flush()
    link.transport.poll()
    assert not link.config.fresh
    ready(link)
    names = link.server.getStringArrayTopic("/Spot/cameras").subscribe([])
    try:
        wait(link, lambda: names.get() == ["front"])
        assert link.config.camera("front").binding_id == "usb-a"
        assert len(link.applied) == 1
    finally:
        names.close()


def test_zero_tag_frame_keeps_capture_timestamp_mount_and_configuration_revision(link):
    ready(link)
    message, captured = observation(link)
    assert link.transport.publish(message, captured)
    wait(link, lambda: link.frames.get().sequence == 1)
    sample = link.frames.getAtomic()
    assert sample.value.candidateCount == 0
    assert sample.value.robotToCamera.X() == pytest.approx(0.2)
    assert sample.value.robotToCamera.Z() == pytest.approx(0.5)
    assert (sample.value.revisionHigh, sample.value.revisionLow) == session(
        link.config.state.generation
    )
    assert abs(sample.time - message.capture_local_nt_us) < 2000


def test_settings_change_rejects_inflight_observations_without_acknowledgement(link):
    ready(link)
    old, captured = observation(link)
    link.config.tune("front", {"gain": 4}, link.config.state.generation)
    link.transport.configuration_applied()
    assert not link.transport.publish(old, captured)
    current, captured = observation(link)
    assert link.transport.publish(current, captured)
    assert link.config.effective_controls("front")["gain"] == 4


def test_reconnect_reapplies_defaults_and_withholds_preconnection_frames(link):
    ready(link)
    old, captured = observation(link)
    link.client.stopClient()
    wait(link, lambda: not link.config.connected)
    assert link.transport.context("front", time.monotonic_ns(), 0) is None
    link.client.startClient4("spot-test")
    wait(link, lambda: link.config.fresh and link.config.tag_selection() is not None)
    assert not link.transport.publish(old, captured)
    current, captured = observation(link)
    assert link.transport.publish(current, captured)


def test_policy_change_rejects_inflight_solve_without_reapplying_configuration(link):
    ready(link)
    old, captured = observation(link)
    link.states.set(wire.RobotState(2, [2]))
    wait(link, lambda: link.config.tag_selection().generation == 2)
    assert not link.transport.publish(old, captured)
    assert len(link.applied) == 1
    current, captured = observation(link)
    assert link.transport.publish(current, captured)


def test_binary_robot_decision_is_exposed_only_while_capture_is_fresh(link):
    ready(link)
    publisher = link.server.getStructTopic("/Spot/front/decision", RobotDecision).publish()
    try:
        offset = link.transport.clock.snapshot().offset_us
        now = (nt_now_us() + offset) / 1e6
        publisher.set(RobotDecision(*session("2" * 32), 1, now, 0, True, True))
        wait(link, lambda: "front" in link.transport.robot_decisions)
        decision = link.transport.robot_decisions["front"]
        assert decision["capture_epoch"] == "2" * 32
        assert decision["state"] == "ACCEPTED" and decision["fused"]
        publisher.set(RobotDecision(*session("2" * 32), 1, now - 1, 0, True, True))
        wait(link, lambda: not link.transport.robot_decisions)
    finally:
        publisher.close()
