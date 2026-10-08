from __future__ import annotations

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from beta_fixtures import manifest

from spot_vision.beta_runtime import BetaRuntime
from spot_vision.clock import ClockGate
from spot_vision.config import ConfigError, NtConfig
from spot_vision.configuration import mode_signature
from spot_vision.devices import DeviceManager, DeviceNode, DeviceRegistry
from spot_vision.models import CameraCounters, DetectionBatch, FramePacket
from spot_vision.proto import vision_v2_pb2 as wire
from spot_vision.queues import LatestFrameSlot


class Transport:
    def __init__(self, nt, config, cameras):
        self.configuration, self.cameras = config, cameras
        self.clock = ClockGate()
        self.published = []

    def poll(self):
        pass

    def acknowledge(self):
        pass

    def invalidate_configuration(self):
        pass

    def heartbeat(self, *args):
        pass

    def context(self, *args):
        return None

    def close(self):
        pass


class Capture:
    def __init__(self, camera, device, generation, controls, observer):
        self.camera, self.device, self.generation = camera, device, generation
        self.requested, self.readback = controls.copy(), controls.copy()
        self._lock = threading.RLock()
        self.slot, self.counters = LatestFrameSlot(), CameraCounters()
        self.verified, self.frame = False, None
        self.ready = threading.Event()
        self.last_progress = time.monotonic()
        self.updates, self.stopped = [], False

    def start(self):
        self.verified = True
        self.ready.set()

    def update(self, generation, controls):
        if controls.get("gain") == 99:
            raise ConfigError("device rejected gain")
        self.generation = generation
        self.readback, self.requested = controls.copy(), controls.copy()
        self.updates.append(controls.copy())
        self.slot.take()

    def stop(self):
        self.stopped, self.verified = True, False

    def is_alive(self):
        return not self.stopped


@pytest.fixture
def runtime(tmp_path):
    nodes = [DeviceNode("/dev/video0", "usb-a", "1", "2", "serial", "camera", True)]
    registry = DeviceRegistry(tmp_path)
    devices = DeviceManager(
        registry,
        enumerate_fn=lambda: nodes,
        capability_fn=lambda _: (
            """
        [0]: 'MJPG'
            Size: Discrete 640x480
                Interval: Discrete 0.033s (30.000 fps)
                 gain 0x00980913 (int) : min=0 max=100 step=1 default=1 value=1
                 contrast 0x00980901 (int) : min=0 max=32 step=1 default=16 value=16
    """
        ),
    )
    devices.refresh()
    constructed = []

    def detector(camera, calibration):
        constructed.append((camera, calibration))
        return SimpleNamespace(detect=lambda _: DetectionBatch((), 1))

    runtime = BetaRuntime(
        tmp_path,
        NtConfig(enabled=False),
        backend="cpu",
        devices=devices,
        transport_factory=Transport,
        capture_factory=Capture,
        detector_factory=detector,
    )
    runtime.configuration.connection_changed(True)
    runtime.configuration.accept_manifest(manifest())
    runtime.configuration.robot_state(
        wire.RobotState(robot_session="robot-1", enabled=False, sequence=1)
    )
    identity = devices.snapshot()[0]["identity"]
    runtime.configuration.rename(identity, "front", runtime.configuration.state.generation)
    return runtime, identity, nodes, constructed


def test_runtime_tuning_retains_single_capture_owner_and_detector(runtime):
    app, identity, _, built = runtime
    worker = app.workers[identity]
    before = len(built)
    old_generation = app.configuration.state.generation
    worker.slot.put(
        FramePacket(
            identity,
            1,
            1,
            1,
            time.monotonic_ns(),
            np.zeros((480, 640, 2), np.uint8),
            "capture",
            old_generation,
        )
    )
    app.configuration.tune("front", {"gain": 2}, old_generation)
    assert app.workers[identity] is worker
    assert worker.readback["gain"] == 2
    assert app.generation == app.configuration.state.generation != old_generation
    assert worker.slot.take() is None
    assert len(built) == before


def test_failed_readback_restores_previous_durable_and_runtime_generation(runtime):
    app, identity, _, _ = runtime
    before = app.configuration.state
    with pytest.raises(ConfigError, match="rejected"):
        app.configuration.tune("front", {"gain": 99}, before.generation)
    assert app.configuration.state == before
    assert app.store.load() == before
    assert app.generation == before.generation
    assert app.workers[identity].readback["gain"] == 1


def test_unsupported_mode_is_not_opened_or_falsely_calibrated(runtime):
    app, identity, _, _ = runtime
    app.devices._devices[identity] = replace(app.devices.get(identity), modes=())
    app.apply(app.configuration.state, app.configuration.manifest)
    assert identity not in app.workers
    generation = app.camera_generations()[0]
    assert not generation.calibration_valid
    assert generation.mode_id == ""
    assert "not advertised" in app.status()["cameras"][0]["fault"]


def test_disconnect_and_reenumeration_preserve_binding_without_estimator_reset(runtime):
    app, identity, nodes, _ = runtime
    old_worker = app.workers[identity]
    nodes.clear()
    app.devices.refresh()
    app.apply(app.configuration.state, app.configuration.manifest)
    assert old_worker.stopped
    assert app.status()["cameras"][0]["name"] == "front"
    assert app.status()["cameras"][0]["fault"] == "Disconnected"
    nodes.append(DeviceNode("/dev/video7", "usb-b", "1", "2", "serial", "camera", True))
    app.devices.refresh()
    app.apply(app.configuration.state, app.configuration.manifest)
    assert app.workers[identity] is not old_worker
    assert app.roles[identity] == "front"
    assert app.configuration.profile_data()["bindings"]["front"]["identity"] == identity


def test_calibration_group_rebuild_failure_cannot_activate(runtime):
    app, identity, _, _ = runtime
    before = app.configuration.state

    def fail(*args):
        raise RuntimeError("native rebuild failed")

    app.detector_factory = fail
    record = {
        "identity": identity,
        "mode_signature": mode_signature(app.modes[identity]),
        "fit": {
            "accepted": True,
            "frames_used": 15,
            "rms_reprojection_error_px": 0.1,
            "coverage": 0.5,
            "diversity": 0.75,
        },
        "holdout": {"accepted": True, "views": 5, "rms_px": 0.2},
        "algorithm": "charuco-fit-holdout-v2",
        "model": "plumb_bob",
        "board": {
            "squares_x": 15,
            "squares_y": 15,
            "square_length_m": 0.03,
            "marker_length_m": 0.022,
            "dictionary": "DICT_4X4_250",
        },
        "image_rotation_deg": 0,
        "intrinsics": {
            "width": 640,
            "height": 480,
            "camera_matrix": [[500, 0, 320], [0, 500, 240], [0, 0, 1]],
            "distortion_coefficients": [0] * 5,
            "reprojection_error_px": 0.1,
        },
    }
    with pytest.raises(ConfigError, match="rebuild failed"):
        app.configuration.calibration_group([record], before.generation, app.validate_calibration)
    assert app.store.load() == before
    assert app.configuration.state == before
    assert not app.camera_generations()[0].calibration_valid


def test_optional_unsupported_control_is_unavailable_without_blocking_camera(runtime):
    from spot_vision.beta_contract import content_hash

    app, identity, _, _ = runtime
    profile = manifest()
    profile.profile.cameras[0].controls.add(name="focus_auto", default_value=0, allow_override=True)
    profile.manifest_hash = content_hash(profile.profile)
    app.configuration.accept_manifest(profile)
    app.configuration.robot_state(
        wire.RobotState(robot_session="robot-1", enabled=False, sequence=2)
    )
    assert app.workers[identity].verified and "focus_auto" not in app.workers[identity].readback
    with pytest.raises(ConfigError, match="unavailable"):
        app.configuration.tune("front", {"focus_auto": 1}, app.configuration.state.generation)


def test_required_unsupported_control_blocks_only_its_camera(runtime):
    from spot_vision.beta_contract import content_hash

    app, identity, _, _ = runtime
    profile = manifest()
    profile.profile.cameras[0].controls.add(name="focus_auto", default_value=0, required=True)
    profile.manifest_hash = content_hash(profile.profile)
    app.configuration.accept_manifest(profile)
    assert identity not in app.workers
    assert "Required controls unavailable" in app.status()["cameras"][0]["fault"]


def test_unnamed_preview_tries_next_mode_only_after_owner_failure(runtime):
    import copy

    from spot_vision.persistence import StateSnapshot

    app, identity, _, _ = runtime
    app.devices._devices[identity] = replace(
        app.devices.get(identity),
        modes=(
            {"width": 640, "height": 480, "fps": 30, "pixel_format": "MJPG"},
            {"width": 320, "height": 240, "fps": 30, "pixel_format": "YUYV"},
        ),
    )
    data = copy.deepcopy(app.configuration.state.data)
    data["profiles"]["test-robot"]["bindings"] = {}
    state = StateSnapshot(app.configuration.state.generation, data)
    app.apply(state, app.configuration.manifest)
    first = app.workers[identity]
    first.verified = False
    first.counters.capture_failures = 1
    app.apply(state, app.configuration.manifest)
    second = app.workers[identity]
    assert first.stopped and second is not first
    assert second.camera.width == 320 and second.camera.format == "YUYV"
    second.verified = False
    second.counters.capture_failures = 1
    app.apply(state, app.configuration.manifest)
    assert app.workers[identity] is second  # exhausted list keeps one bounded recovering owner
