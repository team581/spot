from __future__ import annotations

import copy
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from robot_fixtures import manifest
from spot_vision import protocol_models as wire
from spot_vision.clock import ClockGate
from spot_vision.config import ConfigError, NtConfig
from spot_vision.configuration import mode_signature
from spot_vision.devices import DeviceManager, DeviceNode, DeviceRegistry
from spot_vision.models import (
    CameraCounters,
    DetectedFrame,
    DetectionBatch,
    FramePacket,
    PoseSolution,
)
from spot_vision.queues import LatestFrameSlot
from spot_vision.runtime import Runtime


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

    runtime = Runtime(
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


def test_supervisor_does_not_block_or_report_capture_transitions_as_dead(runtime):
    app, identity, _, _ = runtime
    worker = app.workers[identity]
    worker.name, worker.stopped = "uvc-test", True
    app.threads = []
    app.frames.worker = SimpleNamespace(is_alive=lambda: True)
    app.frames.last_progress = time.monotonic()
    entered, release = threading.Event(), threading.Event()

    def transition():
        with app._pipeline_lock:
            entered.set()
            release.wait(2)

    thread = threading.Thread(target=transition)
    thread.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        assert app.tick()
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        thread.join(2)
    # Once apply has finished, a genuinely stopped owner must still fail health.
    assert not app.tick()
    assert app.fatal == "Workers stalled: uvc-test"


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
    nodes.append(DeviceNode("/dev/video7", "usb-a", "1", "2", "serial", "camera", True))
    app.devices.refresh()
    app.apply(app.configuration.state, app.configuration.manifest)
    assert app.workers[identity] is not old_worker
    assert app.roles[identity] == "front"
    assert app.configuration.profile_data()["bindings"]["front"]["identity"] == identity


@pytest.mark.parametrize("disconnect_at", ["snapshot", "capture"])
def test_disappearance_during_apply_does_not_open_capture(runtime, monkeypatch, disconnect_at):
    app, identity, _, _ = runtime
    app.workers.pop(identity).stop()
    target = "snapshot" if disconnect_at == "snapshot" else "_camera_config"
    owner = app.devices if disconnect_at == "snapshot" else app
    original = getattr(owner, target)

    def disconnect_after(*args):
        result = original(*args)
        app.devices._devices.clear()
        return result

    monkeypatch.setattr(owner, target, disconnect_after)
    monkeypatch.setattr(app, "capture_factory", lambda *args: pytest.fail("Opened missing camera"))
    with pytest.raises(ConfigError, match="no longer"):
        app.apply(app.configuration.state, app.configuration.manifest)
    assert identity not in app.workers


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
    from spot_vision.contract import content_hash

    app, identity, _, _ = runtime
    profile = manifest()
    profile.profile.cameras[0].controls.append(
        wire.ControlPolicy(name="focus_auto", default_value=0, allow_override=True)
    )
    profile.manifest_hash = content_hash(profile.profile)
    app.configuration.accept_manifest(profile)
    app.configuration.robot_state(
        wire.RobotState(robot_session="robot-1", enabled=False, sequence=2)
    )
    assert app.workers[identity].verified and "focus_auto" not in app.workers[identity].readback
    with pytest.raises(ConfigError, match="unavailable"):
        app.configuration.tune("front", {"focus_auto": 1}, app.configuration.state.generation)


def test_required_unsupported_control_blocks_only_its_camera(runtime):
    from spot_vision.contract import content_hash

    app, identity, _, _ = runtime
    profile = manifest()
    profile.profile.cameras[0].controls.append(
        wire.ControlPolicy(name="focus_auto", default_value=0, required=True)
    )
    profile.manifest_hash = content_hash(profile.profile)
    app.configuration.accept_manifest(profile)
    assert identity not in app.workers
    assert "Required controls unavailable" in app.status()["cameras"][0]["fault"]


def test_unnamed_preview_tries_next_mode_only_after_owner_failure(runtime):

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


@pytest.mark.parametrize("width,height,fps", [(640, 480, 120), (640, 400, 210), (1920, 1080, 30)])
def test_unnamed_camera_can_preview_advertised_high_speed_or_full_hd_mode(
    runtime, width, height, fps
):

    from spot_vision.persistence import StateSnapshot

    app, identity, _, _ = runtime
    app.devices._devices[identity] = replace(
        app.devices.get(identity),
        modes=({"width": width, "height": height, "fps": fps, "pixel_format": "MJPG"},),
    )
    data = copy.deepcopy(app.configuration.state.data)
    data["profiles"]["test-robot"]["bindings"] = {}
    app.apply(StateSnapshot(app.configuration.state.generation, data), app.configuration.manifest)
    worker = app.workers[identity]
    assert (worker.camera.width, worker.camera.height, worker.camera.fps) == (width, height, fps)
    camera = app.status()["cameras"][0]
    assert identity not in app.roles
    assert camera["present"] and camera["connected"]


def test_preview_prefers_low_bandwidth_modes_and_rejects_excessive_capture_load(runtime):

    from spot_vision.persistence import StateSnapshot

    app, identity, _, _ = runtime
    app.devices._devices[identity] = replace(
        app.devices.get(identity),
        modes=(
            {"width": 640, "height": 480, "fps": 120, "pixel_format": "MJPG"},
            {"width": 320, "height": 240, "fps": 30, "pixel_format": "MJPG"},
            {"width": 1920, "height": 1080, "fps": 240, "pixel_format": "MJPG"},
        ),
    )
    data = copy.deepcopy(app.configuration.state.data)
    data["profiles"]["test-robot"]["bindings"] = {}
    state = StateSnapshot(app.configuration.state.generation, data)
    app.apply(state, app.configuration.manifest)
    assert app.workers[identity].camera.width == 320
    app.devices._devices[identity] = replace(
        app.devices.get(identity), modes=(app.devices.get(identity).modes[-1],)
    )
    app.apply(state, app.configuration.manifest)
    camera = app.status()["cameras"][0]
    assert camera["present"] and not camera["connected"]
    assert "No bounded supported preview mode" in camera["fault"]


def test_unconfigured_camera_can_tune_and_calibrate_at_origin_without_robot(runtime):
    from spot_vision.calibration import CalibrationManager

    app, identity, _, _ = runtime
    config = app.configuration
    config.connection_changed(False)
    config.manifest = None
    config.begin_standalone()
    config._commit({}, config.state.generation)
    config.setup_device(
        identity,
        {"width": 640, "height": 480, "fps": 30, "pixel_format": "MJPG"},
        {"gain": 1, "contrast": 16},
        config.state.generation,
    )
    worker = app.workers[identity]
    config.tune_device(identity, {"gain": 2}, config.state.generation)
    assert app.workers[identity] is worker and worker.readback["gain"] == 2
    status = app.status()["cameras"][0]
    assert not status["logical_name"] and status["standalone_setup"]
    assert status["geometry"]["translation"] == [0, 0, 0]
    assert status["geometry"]["quaternion"] == [1, 0, 0, 0]
    assert next(c for c in status["controls"] if c["name"] == "gain")["allowed"]
    app.calibration = CalibrationManager(app)
    app.calibration.command(
        "select", {"identities": [identity], "revision": config.state.generation}
    )
    assert identity in app.calibration.cameras
    assert not app.roles and app.camera_generations() == []
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
    config.calibration_group([record], config.state.generation, app.validate_calibration)
    assert app.status()["cameras"][0]["calibrated"]
    assert app.store.load().data["calibrations"]
    assert config.manifest is None and not config.state.data.get("profiles")
    config.connection_changed(True)
    with pytest.raises(ConfigError, match="locked"):
        config.tune_device(identity, {"gain": 3}, config.state.generation)


def test_exposure_api_and_control_range_use_capture_mode_not_detection_limit(runtime):
    app, identity, _, _ = runtime
    device = app.devices.get(identity)
    exposure = {
        "name": "exposure_time_absolute",
        "type": "int",
        "label": "Exposure",
        "min": 50,
        "max": 10000,
        "step": 1,
        "default": 50,
        "value": 50,
        "factor": 100,
        "unit": "µs",
        "writable": True,
        "options": [],
        "flags": "",
    }
    app.devices._devices[identity] = replace(device, controls=(*device.controls, exposure))
    app.modes[identity].fps = 120
    control = next(
        c for c in app.status()["cameras"][0]["controls"] if c["name"] == "exposure_time_absolute"
    )
    assert control["max"] == 8300 and control["hardware_max"] == 1_000_000
    app._validate_exposure(identity, {"exposure_time_absolute": 8300})
    with pytest.raises(ConfigError, match="maximum 8300"):
        app._validate_exposure(identity, {"exposure_time_absolute": 8400})


def test_moving_usb_port_does_not_move_robot_name_and_return_restores_saved_tuning(runtime):
    app, identity, nodes, _ = runtime
    config = app.configuration
    config.tune("front", {"gain": 2}, config.state.generation)
    saved = config.state
    original = nodes[0]
    nodes[0] = replace(original, path="/dev/video8", topology="different-port")
    app.devices.refresh()
    app.apply(config.state, config.manifest)
    connected = next(c for c in app.status()["cameras"] if c["connected"])
    missing = next(c for c in app.status()["cameras"] if c["logical_name"] == "front")
    assert connected["identity"] != identity and connected["logical_name"] is None
    assert not missing["connected"] and missing["identity"] == identity
    nodes[0] = replace(original, path="/dev/video10")
    app.devices.refresh()
    app.apply(config.state, config.manifest)
    returned = next(c for c in app.status()["cameras"] if c["logical_name"] == "front")
    assert returned["connected"] and returned["identity"] == identity
    assert app.workers[identity].readback["gain"] == 2
    assert config.state == saved


def test_status_reports_detection_latency_with_frame_identity(runtime):
    app, identity, _, _ = runtime
    frame = FramePacket(
        identity,
        17,
        19,
        1,
        time.monotonic_ns(),
        np.zeros((480, 640, 2), np.uint8),
        "capture-test",
        app.generation,
    )
    app.frames.result(DetectedFrame(frame, DetectionBatch((), 4.5), 7.25), PoseSolution())
    metrics = next(c for c in app.status()["cameras"] if c["identity"] == identity)["metrics"]
    assert metrics["processed_sequence"] == 17
    assert metrics["processed_capture_epoch"] == "capture-test"
    assert metrics["detect_ms"] == 4.5
    assert metrics["capture_to_detect_ms"] == 7.25
    assert metrics["tag_ids"] == []


def test_network_changes_run_outside_camera_configuration_queue(runtime):
    from spot_vision.networking import NetworkClient

    app, _, _, _ = runtime
    app.network = NetworkClient()
    calls = []
    app.network.request = lambda operation, payload: (
        calls.append(threading.current_thread().name) or {}
    )
    try:
        assert app.submit(
            "network/apply", {"interface": "eth0", "mode": "automatic", "address": ""}
        ).result(1) == {"result": {}}
        assert calls[0].startswith("network-change")
        assert app.commands.empty()
        app.configuration.robot_state(
            wire.RobotState(robot_session="robot-1", enabled=True, sequence=2)
        )
        with pytest.raises(ConfigError, match="locked"):
            app.submit("network/apply", {}).result(1)
        # Recovery must remain possible even when the robot state changes.
        assert app.submit("network/revert", {"token": "a" * 32}).result(1) == {"result": {}}
    finally:
        app.network.close()


def test_omitted_code_control_remains_editable_and_reapplied(runtime):
    from spot_vision.contract import content_hash

    app, identity, _, _ = runtime
    app.configuration.tune("front", {"gain": 7}, app.configuration.state.generation)
    updated = manifest()
    retained = [c for c in updated.profile.cameras[0].controls if c.name != "gain"]
    del updated.profile.cameras[0].controls[:]
    updated.profile.cameras[0].controls.extend(retained)
    updated.manifest_hash = content_hash(updated.profile)
    app.configuration.accept_manifest(updated)
    app.configuration.robot_state(
        wire.RobotState(robot_session="robot-1", enabled=False, sequence=2)
    )
    assert app.workers[identity].readback["gain"] == 7
    cap = next(c for c in app.status()["cameras"][0]["controls"] if c["name"] == "gain")
    assert cap["allowed"] and cap["default"] is None
    app.configuration.tune("front", {"gain": 8}, app.configuration.state.generation)
    assert app.workers[identity].readback["gain"] == 8
