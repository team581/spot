from __future__ import annotations

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from robot_fixtures import manifest
from spot_vision import protocol_models as wire
from spot_vision.clock import SyncSnapshot
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
        self.clock = SimpleNamespace(snapshot=lambda: SyncSnapshot("Waiting", None))
        self.published = []
        self.nt = nt
        self.invalidations = 0

    def set_endpoint(self, nt):
        self.nt = nt
        self.configuration.connection_changed(False)

    def poll(self):
        pass

    def configuration_applied(self):
        pass

    def invalidate_configuration(self):
        self.invalidations += 1

    def heartbeat(self, *args):
        pass

    def context(self, *args):
        return None

    def close(self):
        pass


class Capture:
    def __init__(self, camera, device, generation, controls, observer, *, reset_defaults=False):
        self.camera, self.device, self.generation = camera, device, generation
        self.requested, self.readback = controls.copy(), controls.copy()
        self.reset_defaults = reset_defaults
        self._lock = threading.RLock()
        self.slot, self.counters = LatestFrameSlot(), CameraCounters()
        self.verified, self.frame = False, None
        self.controls_rejected = False
        self.ready = threading.Event()
        self.last_progress = time.monotonic()
        self.updates, self.stopped = [], False

    def start(self):
        self.verified = True
        self.ready.set()

    def update(self, generation, controls, *, reset_defaults=False):
        if controls.get("gain") == 99:
            raise ConfigError("device rejected gain")
        self.generation = generation
        self.reset_defaults = reset_defaults
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
    runtime.configuration.robot_state(wire.RobotState())
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
    invalidations = app.transport.invalidations
    old_generation = app.configuration.state.generation
    worker.slot.put(
        FramePacket(
            identity,
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
    assert app.transport.invalidations == invalidations + 1


def test_failed_readback_restores_previous_durable_and_runtime_generation(runtime):
    app, identity, _, _ = runtime
    before = app.configuration.state
    with pytest.raises(ConfigError, match="rejected"):
        app.configuration.tune("front", {"gain": 99}, before.generation)
    assert app.configuration.state == before
    assert app.store.load().data == before.data
    assert app.generation == before.generation
    assert app.workers[identity].readback["gain"] == 1


def test_camera_that_rejected_its_controls_restarts_with_edited_values(runtime):
    app, identity, _, _ = runtime
    stuck = app.workers[identity]
    stuck.verified, stuck.controls_rejected = False, True
    assert app.status()["cameras"][0]["controls_rejected"]
    app.configuration.tune("front", {"gain": 5}, app.configuration.state.generation)
    worker = app.workers[identity]
    assert worker is not stuck and stuck.stopped
    assert worker.verified and worker.requested["gain"] == 5


def test_unsupported_mode_is_not_opened_or_falsely_calibrated(runtime):
    app, identity, _, _ = runtime
    app.devices._devices[identity] = replace(app.devices.get(identity), modes=())
    app.apply(app.configuration.state, app.configuration.manifest)
    assert identity not in app.workers
    assert not app.camera_ready("front")
    assert "not advertised" in app.status()["cameras"][0]["fault"]


def test_configured_latency_shifts_capture_timestamps(runtime):
    app, identity, _, _ = runtime
    worker = app.workers[identity]
    assert worker.timestamp_correction_us == -5000
    slower = manifest()
    slower.profile.latency_ms = 12
    app.configuration.accept_manifest(slower)
    assert worker.timestamp_correction_us == -12000


def test_dashboard_can_switch_to_an_advertised_mode_robot_code_lacks(runtime):
    app, identity, _, _ = runtime
    unsupported = manifest()
    unsupported.profile.cameras[0].allowed_modes[0].fps = 60
    assert [m["id"] for m in app.status()["cameras"][0]["allowed_modes"]] == ["640x480"]
    app.configuration.accept_manifest(unsupported)
    assert identity not in app.workers
    modes = app.status()["cameras"][0]["allowed_modes"]
    assert [(m["id"], m["supported"]) for m in modes] == [
        ("640x480", False),
        ("640x480-30-MJPEG", True),
    ]
    app.threads[0].start()
    try:
        app.submit(
            "camera/mode",
            {
                "name": "front",
                "mode_id": "640x480-30-MJPEG",
                "revision": app.configuration.state.generation,
            },
        ).result(2)
    finally:
        app.stop_event.set()
        app.threads[0].join(2)
    assert app.workers[identity].camera.fps == 30
    [entry] = [e for e in app.configuration.override_entries() if "allowed_modes" in e["path"]]
    assert entry["value"][0]["id"] == "640x480-30-MJPEG"


def test_disconnect_and_reenumeration_preserve_binding_without_estimator_reset(runtime):
    app, identity, nodes, _ = runtime
    old_worker = app.workers[identity]
    invalidations = app.transport.invalidations
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
    assert app.configuration.camera("front").binding_id == identity
    # Other cameras keep publishing while one re-enumerates.
    assert app.transport.invalidations == invalidations


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
    assert app.store.load().data == before.data
    assert app.configuration.state == before
    assert not app.camera_ready("front")


def test_optional_unsupported_control_is_unavailable_without_blocking_camera(runtime):

    app, identity, _, _ = runtime
    profile = manifest()
    profile.profile.cameras[0].controls.append(
        wire.ControlPolicy(name="focus_auto", default_value=0, allow_override=True)
    )
    app.configuration.accept_manifest(profile)
    app.configuration.robot_state(wire.RobotState())
    assert app.workers[identity].verified and "focus_auto" not in app.workers[identity].readback
    with pytest.raises(ConfigError, match="unavailable"):
        app.configuration.tune("front", {"focus_auto": 1}, app.configuration.state.generation)


def test_required_unsupported_control_blocks_only_its_camera(runtime):

    app, identity, _, _ = runtime
    profile = manifest()
    profile.profile.cameras[0].controls.append(
        wire.ControlPolicy(name="focus_auto", default_value=0, required=True)
    )
    app.configuration.accept_manifest(profile)
    assert identity not in app.workers
    assert "Required controls unavailable" in app.status()["cameras"][0]["fault"]


def test_unnamed_preview_tries_next_mode_only_after_owner_failure(runtime):

    app, identity, _, _ = runtime
    app.devices._devices[identity] = replace(
        app.devices.get(identity),
        modes=(
            {"width": 640, "height": 480, "fps": 30, "pixel_format": "MJPG"},
            {"width": 320, "height": 240, "fps": 30, "pixel_format": "YUYV"},
        ),
    )
    settings = app.configuration.export_configuration()
    settings.cameras[0].binding_id = ""
    app.configuration.configure(settings, app.configuration.state.generation)
    state = app.configuration.state
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

    app, identity, _, _ = runtime
    app.devices._devices[identity] = replace(
        app.devices.get(identity),
        modes=({"width": width, "height": height, "fps": fps, "pixel_format": "MJPG"},),
    )
    settings = app.configuration.export_configuration()
    settings.cameras[0].binding_id = ""
    app.configuration.configure(settings, app.configuration.state.generation)
    worker = app.workers[identity]
    assert (worker.camera.width, worker.camera.height, worker.camera.fps) == (width, height, fps)
    camera = app.status()["cameras"][0]
    assert identity not in app.roles
    assert camera["present"] and camera["connected"]


def test_preview_prefers_low_bandwidth_modes_and_rejects_excessive_capture_load(runtime):

    app, identity, _, _ = runtime
    app.devices._devices[identity] = replace(
        app.devices.get(identity),
        modes=(
            {"width": 640, "height": 480, "fps": 120, "pixel_format": "MJPG"},
            {"width": 320, "height": 240, "fps": 30, "pixel_format": "MJPG"},
            {"width": 1920, "height": 1080, "fps": 240, "pixel_format": "MJPG"},
        ),
    )
    settings = app.configuration.export_configuration()
    settings.cameras[0].binding_id = ""
    app.configuration.configure(settings, app.configuration.state.generation)
    state = app.configuration.state
    assert app.workers[identity].camera.width == 320
    app.devices._devices[identity] = replace(
        app.devices.get(identity), modes=(app.devices.get(identity).modes[-1],)
    )
    app.apply(state, app.configuration.manifest)
    camera = app.status()["cameras"][0]
    assert camera["present"] and not camera["connected"]
    assert "No bounded supported preview mode" in camera["fault"]


def test_named_camera_can_tune_and_calibrate_while_robot_is_disconnected(runtime):
    from spot_vision.calibration import CalibrationManager

    app, identity, _, _ = runtime
    config = app.configuration
    config.connection_changed(False)
    worker = app.workers[identity]
    config.tune("front", {"gain": 2}, config.state.generation)
    assert app.workers[identity] is worker and worker.readback["gain"] == 2
    status = app.status()["cameras"][0]
    assert next(c for c in status["controls"] if c["name"] == "gain")["allowed"]
    app.calibration = CalibrationManager(app)
    app.calibration.command(
        "select", {"identities": [identity], "revision": config.state.generation}
    )
    assert identity in app.calibration.cameras
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
    assert {entry["path"] for entry in config.override_entries()} >= {
        "cameras/front/calibration",
        "cameras/front/controls/gain",
    }


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
        "factor": 0.1,
        "unit": "ms",
        "writable": True,
        "options": [],
        "flags": "",
    }
    app.devices._devices[identity] = replace(device, controls=(*device.controls, exposure))
    app.modes[identity].fps = 120
    control = next(
        c for c in app.status()["cameras"][0]["controls"] if c["name"] == "exposure_time_absolute"
    )
    assert control["max"] == 8.3 and control["hardware_max"] == 1000
    app._validate_exposure(identity, {"exposure_time_absolute": 8.3})
    with pytest.raises(ConfigError, match="maximum 8.3 ms"):
        app._validate_exposure(identity, {"exposure_time_absolute": 8.4})


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
        assert app.submit("network/apply", {"mode": "automatic", "address": ""}).result(1) == {
            "result": {}
        }
        assert calls[0].startswith("network-change")
        assert app.commands.empty()
        assert app.submit("network/apply", {}).result(1) == {"result": {}}
        # Recovery runs on the same independent network worker.
        assert app.submit("network/revert", {"token": "a" * 32}).result(1) == {"result": {}}
    finally:
        app.network.close()


def test_omitted_code_control_remains_editable_and_reapplied(runtime):

    app, identity, _, _ = runtime
    app.configuration.tune("front", {"gain": 7}, app.configuration.state.generation)
    updated = manifest()
    retained = [c for c in updated.profile.cameras[0].controls if c.name != "gain"]
    del updated.profile.cameras[0].controls[:]
    updated.profile.cameras[0].controls.extend(retained)
    app.configuration.accept_manifest(updated)
    app.configuration.robot_state(wire.RobotState())
    assert app.workers[identity].readback["gain"] == 7
    cap = next(c for c in app.status()["cameras"][0]["controls"] if c["name"] == "gain")
    assert cap["allowed"] and cap["default"] is None
    app.configuration.tune("front", {"gain": 8}, app.configuration.state.generation)
    assert app.workers[identity].readback["gain"] == 8


def test_team_change_persists_outside_camera_profiles_and_reloads(runtime, tmp_path):
    app, _, _, _ = runtime
    generation = app.configuration.state.generation
    worker = next(iter(app.workers.values()))
    app.threads[0].start()
    try:
        result = app.submit("nt/endpoint", {"team": 9991}).result(2)
        assert result["result"] == {"team": 9991}
        assert app.transport.nt.team == app.endpoint["team"] == 9991
        assert app.transport.nt.server is None
        assert not app.configuration.connected and not app.configuration.fresh
        assert app.configuration.state.generation == generation
        assert next(iter(app.workers.values())) is worker
        restarted = Runtime(
            tmp_path,
            NtConfig(team=581, server="old-server"),
            backend="cpu",
            devices=app.devices,
            transport_factory=Transport,
        )
        try:
            assert restarted.transport.nt.team == restarted.endpoint["team"] == 9991
            assert restarted.transport.nt.server is None
        finally:
            restarted.close()
    finally:
        app.stop_event.set()
        app.threads[0].join(2)


def test_team_change_does_not_require_disabled_robot(runtime):
    app, _, _, _ = runtime
    assert app.set_nt_endpoint({"team": 9991}) == {"team": 9991}
    assert app.nt_settings.exists()


def test_disconnected_team_can_be_corrected_and_failed_save_restores_endpoint(runtime, monkeypatch):
    from spot_vision import runtime as runtime_module

    app, _, _, _ = runtime
    app.configuration.connection_changed(False)
    assert app.set_nt_endpoint({"team": 9991}) == {"team": 9991}
    saved = app.nt_settings.read_bytes()

    def fail_save(*args):
        raise OSError("disk full")

    monkeypatch.setattr(runtime_module, "durable_replace", fail_save)
    with pytest.raises(OSError, match="disk full"):
        app.set_nt_endpoint({"team": 581})
    assert app.transport.nt.team == app.endpoint["team"] == 9991
    assert app.nt_settings.read_bytes() == saved


def test_server_address_replaces_team_and_reloads(runtime, tmp_path):
    app, _, _, _ = runtime
    assert app.set_nt_endpoint({"server": "10.0.0.5"}) == {"server": "10.0.0.5"}
    assert app.transport.nt.server == app.endpoint["configured"] == "10.0.0.5"
    assert app.transport.nt.team is app.endpoint["team"] is None
    restarted = Runtime(
        tmp_path,
        NtConfig(team=581),
        backend="cpu",
        devices=app.devices,
        transport_factory=Transport,
    )
    try:
        assert restarted.transport.nt.server == "10.0.0.5"
        assert restarted.transport.nt.team is None
    finally:
        restarted.close()


def test_pose_solver_uses_robot_supplied_camera_mount(runtime):
    """A raised, pitched camera must solve to its true pose, not a level camera at the floor."""
    from wpimath.geometry import Pose3d, Rotation3d, Transform3d, Translation3d

    from spot_vision.models import Detection

    app, identity, _, _ = runtime
    config = app.configuration
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
    # A mount-only change must reach the solver without a new calibration or capture owner.
    worker = app.workers[identity]
    robot_manifest = manifest()
    robot_manifest.profile.cameras[0].robot_to_camera = wire.Mount(
        x_m=0.2, y_m=-0.1, z_m=0.35, pitch_deg=-15, yaw_deg=10
    )
    config.accept_manifest(robot_manifest)
    assert app.workers[identity] is worker

    # Project with WPILib geometry, independent of Spot's pose helpers. The robot sits
    # on the floor facing the tags, which face field +X.
    field_to_robot = Pose3d(7, 0.5, 0, Rotation3d(0, 0, np.pi))
    camera = field_to_robot.transformBy(
        Transform3d(Translation3d(0.2, -0.1, 0.35), Rotation3d(0, np.radians(-15), np.radians(10)))
    )
    half = 0.1651 / 2
    detections = []
    for tag in robot_manifest.profile.field.tags:
        center = Pose3d(
            tag.field_to_tag.x_m, tag.field_to_tag.y_m, tag.field_to_tag.z_m, Rotation3d()
        )
        pixels = []
        # FIRST decoded order: bottom left/right, top right/left as seen facing the tag.
        for dy, dz in ((-half, -half), (half, -half), (half, half), (-half, half)):
            corner = center.transformBy(Transform3d(0, dy, dz, Rotation3d())).relativeTo(camera)
            pixels.append(
                [320 - 500 * corner.Y() / corner.X(), 240 - 500 * corner.Z() / corner.X()]
            )
        detections.append(Detection(tag.id, np.array(pixels)))

    solution = app.solvers[identity].solve(tuple(detections))
    best = min(solution.candidates, key=lambda c: c.reprojection_error_px)
    assert best.reprojection_error_px < 1e-3
    assert np.allclose(best.translation, [camera.X(), camera.Y(), camera.Z()], atol=1e-4)
