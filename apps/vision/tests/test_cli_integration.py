"""Exercise public commands with real images and controlled IO failures."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from spot_vision import cli
from spot_vision.config import load_config
from spot_vision.models import Detection, DetectionBatch
from spot_vision.regression import run_image_regression

DATA = Path(__file__).parent / "data/regression"


def command(name, *extra):
    return [name, "--config", str(DATA / "config.json"), "--camera", "front", *extra]


@pytest.mark.parametrize(
    "image,ids", [("center.png", [1]), ("multi.png", [1, 2]), ("blank.png", [])]
)
def test_replay_command_emits_actual_native_detections(capsys, image, ids):
    assert cli.main(command("replay", "--input", str(DATA / image), "--frames", "1")) == 0
    output = json.loads(capsys.readouterr().out)
    assert sorted(tag["id"] for tag in output["tags"]) == ids
    assert output["sequence"] == 1 and output["detect_ms"] > 0
    assert all(len(tag["corners"]) == 4 for tag in output["tags"])


def test_benchmark_command_measures_real_detector(capsys):
    assert cli.main(command("benchmark", "--input", str(DATA / "multi.png"))) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["backend"] == "cpu" and report["frames"] == 1
    assert report["detections"] == 2
    assert report["mean_detect_ms"] > 0 and report["processed_fps"] > 0


def test_validate_calibration_loads_actual_layout(capsys):
    assert cli.main(command("validate-calibration")) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["resolution"] == [1280, 800]
    assert report["field_revision"] > 0


def test_image_regression_command_writes_same_json_as_stdout(tmp_path, capsys):
    path = tmp_path / "report.json"
    assert (
        cli.main(
            [
                "image-regression",
                "--manifest",
                str(DATA / "manifest.json"),
                "--repeats",
                "1",
                "--output",
                str(path),
            ]
        )
        == 0
    )
    assert json.loads(path.read_text()) == json.loads(capsys.readouterr().out)
    assert json.loads(path.read_text())["passed"]


def test_failed_regression_command_returns_one_and_retains_report(monkeypatch, tmp_path, capsys):
    from spot_vision import regression

    report = {"passed": False, "cases": [{"failures": ["tag_ids"]}]}
    monkeypatch.setattr(regression, "run_image_regression", lambda *a, **_kw: report)
    path = tmp_path / "failure.json"
    assert cli.main(["image-regression", "--manifest", "unused", "--output", str(path)]) == 1
    assert json.loads(path.read_text()) == report


@pytest.mark.parametrize("repeats", ["0", "-1"])
def test_invalid_regression_repeat_count_fails_without_creating_output(repeats, tmp_path):
    path = tmp_path / "report.json"
    assert (
        cli.main(
            [
                "image-regression",
                "--manifest",
                "unused",
                "--repeats",
                repeats,
                "--output",
                str(path),
            ]
        )
        == 2
    )
    assert not path.exists()


@pytest.mark.parametrize("name", ["replay", "benchmark", "validate-calibration", "camera-modes"])
def test_unknown_camera_returns_configuration_error(name):
    args = [name, "--config", str(DATA / "config.json"), "--camera", "missing"]
    if name in {"replay", "benchmark"}:
        args.extend(["--input", str(DATA / "center.png")])
    assert cli.main(args) == 2


@pytest.mark.parametrize("repeats,backend", [(0, "cpu"), (-1, "cpu"), (1, "magic")])
def test_regression_api_validates_arguments_before_loading_manifest(repeats, backend):
    with pytest.raises(ValueError):
        run_image_regression("does-not-exist", repeats=repeats, backend=backend)


def test_regression_api_rejects_empty_corpus(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"config": str((DATA / "config.json").resolve()), "cases": []}))
    with pytest.raises(ValueError, match="at least one case"):
        run_image_regression(manifest)


def test_recording_resolution_mismatch_is_visible():
    camera = replace(load_config(DATA / "config.json").camera("front"), width=640, height=480)
    with pytest.raises(RuntimeError, match="expected 640x480"):
        list(cli._recording_frames(DATA / "center.png", camera))


@pytest.mark.parametrize("scenario", ["eof", "close", "wrong_size"])
def test_video_capture_is_released_on_eof_early_close_and_error(monkeypatch, scenario):
    camera = load_config(DATA / "config.json").camera("front")
    image = np.zeros((camera.height, camera.width, 3), np.uint8)
    if scenario == "wrong_size":
        image = image[:20]

    class Capture:
        released = False
        reads = 0

        def isOpened(self):
            return True

        def read(self):
            self.reads += 1
            return (True, image) if self.reads == 1 else (False, None)

        def release(self):
            self.released = True

    capture = Capture()
    monkeypatch.setattr(cv2, "imread", lambda *_: None)
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_: capture)
    frames = cli._recording_frames("video.mp4", camera)
    if scenario == "wrong_size":
        with pytest.raises(RuntimeError, match="recording is"):
            next(frames)
    elif scenario == "close":
        assert next(frames).shape == (camera.height, camera.width, 2)
        frames.close()
    else:
        assert len(list(frames)) == 1
    assert capture.released


def test_benchmark_empty_video_returns_error(monkeypatch):
    monkeypatch.setattr(cli, "_recording_frames", lambda *_: iter(()))
    assert cli.main(command("benchmark", "--input", "empty.mp4")) == 2


@pytest.mark.parametrize("mismatch", [False, True])
def test_compare_forbids_gpu_fallback_and_reports_id_mismatches(monkeypatch, capsys, mismatch):
    cameras = []

    def detector(camera, calibration):
        cameras.append(camera)
        tag_id = 2 if mismatch and camera.detector.backend == "cuda" else 1
        corners = np.zeros((4, 2)) + (1 if camera.detector.backend == "cuda" else 0)
        return SimpleNamespace(detect=lambda _: DetectionBatch((Detection(tag_id, corners),), 1))

    monkeypatch.setattr(cli, "create_detector", detector)
    result = cli.main(command("compare", "--input", str(DATA / "center.png"), "--frames", "1"))
    assert result == int(mismatch)
    assert [camera.detector.backend for camera in cameras] == ["cuda", "cpu"]
    report = json.loads(capsys.readouterr().out)
    assert report["id_mismatches"] == int(mismatch)
    assert report["max_corner_delta_px"] == (0 if mismatch else 1)


def test_charuco_empty_input_does_not_write_a_calibration(tmp_path, capsys):
    target = tmp_path / "calibration.json"
    assert (
        cli.main(
            [
                "calibrate-charuco",
                "--input-dir",
                str(tmp_path),
                "--output",
                str(target),
                "--width",
                "640",
                "--height",
                "480",
            ]
        )
        == 2
    )
    assert not json.loads(capsys.readouterr().out)["accepted"]
    assert not target.exists()


@pytest.mark.parametrize("extra", [[], ["--config", "unused"], ["--camera", "front"]])
def test_charuco_requires_destination_and_paired_config_camera(tmp_path, extra):
    assert (
        cli.main(
            [
                "calibrate-charuco",
                "--input-dir",
                str(tmp_path),
                "--width",
                "640",
                "--height",
                "480",
                *extra,
            ]
        )
        == 2
    )


@pytest.mark.parametrize("mode", ["frame", "worker_exit", "interrupt"])
@pytest.mark.parametrize("auto_exposure", [False, True])
def test_probe_shuts_down_capture_on_success_exit_and_interrupt(
    monkeypatch, capsys, mode, auto_exposure
):
    import threading
    import time

    from spot_vision.models import CameraCounters, FramePacket
    from spot_vision.queues import LatestFrameSlot

    instances = []
    image = next(
        cli._recording_frames(
            DATA / "center.png", load_config(DATA / "config.json").camera("front")
        )
    )
    config = load_config(DATA / "config.json")
    camera = replace(config.camera("front"), auto_exposure=auto_exposure, exposure_us=5000, gain=7)
    monkeypatch.setattr(cli, "load_config", lambda _: replace(config, cameras=(camera,)))

    class Capture:
        stopped = False

        def __init__(self, camera, device, generation, controls, observer):
            assert device == "/dev/fake" and generation == "probe"
            expected = (
                {"exposure_auto": 3, "gain": 7}
                if auto_exposure
                else {
                    "exposure_auto": 1,
                    "exposure_time_absolute": 5000,
                    "gain": 7,
                }
            )
            assert controls == expected
            self.slot = LatestFrameSlot()
            self.counters = CameraCounters()
            self.ready = threading.Event()
            self.verified = False
            instances.append(self)

        def start(self):
            if mode != "worker_exit":
                self.slot.put(FramePacket("front", 7, 1234, time.monotonic_ns(), image))
                self.verified = True
            self.ready.set()

        def is_alive(self):
            return False

        def stop(self):
            self.slot.close()
            self.stopped = True

    monkeypatch.setattr(cli, "CameraCapture", Capture)
    monkeypatch.setattr(cli, "resolve_device", lambda _: "/dev/fake")
    monkeypatch.setattr(cli, "enumerate_camera", lambda _: "camera modes")
    monkeypatch.setattr(
        cli,
        "_run",
        lambda _: (
            "exposure_auto 0x009a0901 (menu) : min=0 max=3 default=3 value=3\n"
            "exposure_time_absolute 0x009a0902 (int) : min=1 max=5000 step=1 value=50"
        ),
    )
    if mode == "interrupt":

        def interrupt(_):
            raise KeyboardInterrupt()

        monkeypatch.setattr(cli, "create_detector", lambda *_: SimpleNamespace(detect=interrupt))
    assert cli.main(command("probe", "--frames", "1")) == (2 if mode == "worker_exit" else 0)
    assert instances[0].stopped
    if mode == "frame":
        report = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert report["sequence"] == 7 and [tag["id"] for tag in report["tags"]] == [1]
