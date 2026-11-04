"""Real detector/solver/wire integration with camera IO replaced by fixed frames."""

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from spot_vision import service as module
from spot_vision.cli import _recording_frames
from spot_vision.config import load_config
from spot_vision.models import CameraState, FramePacket
from spot_vision.proto import VisionFrame
from spot_vision.transport import MemoryPublisher

DATA = Path(__file__).parent / "data/regression"


class Publisher(MemoryPublisher):
    def __init__(self):
        super().__init__()
        self.global_schema = None
        self.calibration_status = {}
        self.close_calls = 0

    def publish_global(self, schema):
        self.global_schema = schema

    def publish_calibration_status(self, camera, provisional):
        self.calibration_status[camera.id] = provisional

    def close(self):
        self.close_calls += 1


@pytest.fixture
def environment(monkeypatch):
    publisher = Publisher()
    monkeypatch.setattr(module, "NtPublisher", lambda *_: publisher)

    # Threads run normally; tests inject frames into their shared slots.
    class Capture(threading.Thread):
        def __init__(self, camera, slot, counters, stop):
            super().__init__(daemon=True)
            self.stop = stop

        def run(self):
            self.stop.wait()

    monkeypatch.setattr(module, "CaptureWorker", Capture)
    return publisher


def await_frames(publisher, count):
    deadline = time.monotonic() + 5
    while len(publisher.frames) < count and time.monotonic() < deadline:
        time.sleep(0.005)
    assert len(publisher.frames) == count


@pytest.mark.parametrize("rotated", [False, True])
def test_four_camera_service_publishes_tag_then_no_tag_and_stops(environment, rotated, tmp_path):
    config = load_config(DATA / ("config_rotated.json" if rotated else "config.json"))
    base = config.camera("front")
    # Disabled cameras must not acquire a detector, slot, publisher or capture thread.
    cameras = []
    for i in range(1, 5):
        calibration = json.loads(base.calibration.read_text())
        calibration["camera_id"] = str(i)
        path = tmp_path / f"calibration-{i}.json"
        path.write_text(json.dumps(calibration))
        cameras.append(replace(base, id=str(i), calibration=path))
    cameras = tuple(cameras)
    config = replace(config, cameras=cameras + (replace(base, id="off", enabled=False),))
    service = module.VisionService(config)
    publisher = environment
    service.start()
    try:
        assert set(service.cameras) == {"1", "2", "3", "4"}
        assert publisher.global_schema == config.schema_version
        assert set(publisher.calibration_status) == set(service.cameras)
        for sequence, name in [(1, "rotated.png" if rotated else "multi.png"), (2, "blank.png")]:
            for camera in cameras:
                image = next(_recording_frames(DATA / name, camera))
                service.slots[camera.id].put(
                    FramePacket(
                        camera.id,
                        sequence,
                        sequence + 10,
                        1000 + sequence,
                        time.monotonic_ns(),
                        image,
                    )
                )
            await_frames(publisher, sequence * 4)
        decoded = [VisionFrame.FromString(frame) for _, frame, _ in publisher.frames]
        for camera in cameras:
            first, empty = [frame for frame in decoded if frame.camera_id == camera.id]
            assert first.sequence == 1 and first.camera_frame_sequence == 11
            assert first.field_revision == service.layout.revision != 0
            assert sorted(tag.id for tag in first.tags) == [1, 2]
            assert all(tag.used_for_pose for tag in first.tags)
            assert len(first.candidates) == 1
            assert empty.sequence == 2 and not empty.tags and not empty.candidates
            poses = [pose for camera_id, pose, _ in publisher.robot_poses if camera_id == camera.id]
            assert np.allclose(poses[0].translation, [2, 0, 0.6], atol=0.15)
            assert poses[1] is None
            assert service.counters[camera.id].detected == 2
            assert service.counters[camera.id].state == CameraState.NO_TARGETS
    finally:
        service.stop()
        service.stop()
    assert publisher.close_calls == 1
    assert not any(
        worker.is_alive()
        for worker in [*service.capture_workers, service.scheduler, service.output_worker]
    )


@pytest.mark.parametrize("missing", ["calibration", "layout"])
def test_bad_pose_configuration_retains_raw_detection_output(environment, tmp_path, missing):
    config = load_config(DATA / "config.json")
    camera = config.camera("front")
    if missing == "calibration":
        camera = replace(camera, calibration=tmp_path / "missing-calibration.json")
    else:
        config = replace(config, field_layout=tmp_path / "missing-layout.json")
    service = module.VisionService(replace(config, cameras=(camera,)))
    service.start()
    try:
        image = next(_recording_frames(DATA / "center.png", camera))
        service.slots[camera.id].put(FramePacket(camera.id, 1, 1, 1234, time.monotonic_ns(), image))
        await_frames(environment, 1)
        message = VisionFrame.FromString(environment.frames[0][1])
        assert [tag.id for tag in message.tags] == [1]
        assert not message.candidates
        assert message.tags[0].rejection_reason == (
            "NO_CALIBRATION" if missing == "calibration" else "NO_FIELD_LAYOUT"
        )
        assert service.counters[camera.id].configuration_error
        assert service.counters[camera.id].state == CameraState.CONFIG_MISMATCH
    finally:
        service.stop()


def test_service_starts_with_no_enabled_cameras_for_discovery(environment):
    config = load_config(DATA / "config.json")
    service = module.VisionService(
        replace(config, cameras=(replace(config.cameras[0], enabled=False),))
    )
    service.start()
    assert not service.capture_workers and not service.cameras
    assert service.output_worker.is_alive()
    service.stop()


def test_stop_before_start_is_safe_and_idempotent(environment):
    service = module.VisionService(load_config(DATA / "config.json"))
    service.stop()
    service.stop()
    assert service.stop_event.is_set() and service.wake_event.is_set()
    assert environment.close_calls == 1


def test_run_forever_closes_resources_if_watchdog_fails(environment, monkeypatch):
    service = module.VisionService(load_config(DATA / "config.json"))
    monkeypatch.setattr(
        service.watchdog, "ping", lambda _: (_ for _ in ()).throw(RuntimeError("watchdog"))
    )
    with pytest.raises(RuntimeError, match="watchdog"):
        service.run_forever()
    assert service.stop_event.is_set() and environment.close_calls == 1
