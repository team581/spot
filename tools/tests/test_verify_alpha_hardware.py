"""Failure injection ensures the live checker cannot certify stale or broken output."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

import pytest

spec = importlib.util.spec_from_file_location(
    "verify_alpha_hardware", Path(__file__).resolve().parents[1] / "verify_alpha_hardware.py")
hardware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hardware)


def camera(sequence=1):
    candidate = {"translation": [1., 2., 3.], "quaternion": [1., 0., 0., 0.],
                 "error_px": .2, "tag_ids": [4]}
    return {"id": "1", "enabled": True, "fresh": True, "restart_required": False,
            "counters": {"captured": 100 * sequence, "detected": 20 * sequence},
            "telemetry": {"sequence": sequence, "detect_ms": 4., "solve_ms": 2.,
                          "tags": [{"id": 4, "hamming": 0,
                                    "corners": [[10, 20], [20, 20], [20, 30], [10, 30]]}],
                          "pose": deepcopy(candidate), "candidates": [candidate]}}


def evaluate(rows=None, **kwargs):
    rows = rows or [camera(1), camera(2)]
    samples = [{"cameras": [row]} for row in rows]
    return hardware.evaluate_samples(samples, 1., {"1": {"decoded": True}}, **kwargs)


def test_valid_live_progress_and_expected_tag_pass():
    report = evaluate(expected_cameras=["1"], expected_ids=[4])
    assert report["passed"]
    assert report["cameras"]["1"]["detect_fps"] == 20
    assert report["cameras"]["1"]["max_reprojection_error_px"] == .2
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("change,reason", [
    (lambda c: c.update(fresh=False), "stale_frame"),
    (lambda c: c.update(restart_required=True), "calibration_restart_required"),
    (lambda c: c["counters"].update(configuration_error="bad lens"), "configuration_error"),
    (lambda c: c["telemetry"].update(tags=[]), "no_visible_tag"),
    (lambda c: c["telemetry"].update(pose=None), "missing_robot_pose"),
    (lambda c: c["telemetry"].update(candidates=[]), "missing_camera_candidates"),
    (lambda c: c["telemetry"]["pose"].update(translation=[float("nan"), 0, 0]), "invalid_translation"),
    (lambda c: c["telemetry"]["pose"].update(quaternion=[2, 0, 0, 0]), "unnormalized_quaternion"),
    (lambda c: c["telemetry"]["pose"].update(quaternion=[1, 0, 0]), "invalid_quaternion"),
    (lambda c: c["telemetry"]["pose"].update(error_px=-1), "invalid_reprojection_error"),
    (lambda c: c["telemetry"]["pose"].update(error_px=float("inf")), "invalid_reprojection_error"),
    (lambda c: c["telemetry"]["pose"].update(error_px=.3), "wrong_selected_candidate"),
    (lambda c: c["telemetry"]["pose"].update(tag_ids=[99]), "pose_uses_unobserved_tags"),
    (lambda c: c["telemetry"]["tags"][0].update(corners=[[1, 2]]), "invalid_corners"),
    (lambda c: c["telemetry"]["tags"][0].update(hamming=-1), "invalid_hamming"),
    (lambda c: c["telemetry"].update(detect_ms=float("nan")), "invalid_detect_ms"),
    (lambda c: c["telemetry"].update(solve_ms=-1), "invalid_solve_ms"),
])
def test_invalid_live_output_is_rejected(change, reason):
    row = camera()
    change(row)
    assert reason in hardware.telemetry_failures(row)
    report = evaluate([row, row])
    assert not report["passed"]
    assert report["cameras"]["1"]["sample_failures"][reason] == 2


def test_wrong_expected_tag_is_rejected():
    assert "expected_tag_missing" in hardware.telemetry_failures(camera(), [5])


def test_missing_requested_camera_is_rejected():
    report = evaluate(expected_cameras=["1", "2"])
    assert not report["passed"] and report["cameras"]["2"]["failures"] == ["camera_missing"]


@pytest.mark.parametrize("counter", ["capture_failures", "decode_failures", "reconnects",
                                     "timestamp_discontinuities"])
def test_new_hardware_failures_fail_while_historical_counts_do_not(counter):
    first, last = camera(1), camera(2)
    first["counters"][counter] = last["counters"][counter] = 100
    assert evaluate([first, last])["passed"]
    last["counters"][counter] += 1
    report = evaluate([first, last])
    assert not report["passed"]
    assert counter in report["cameras"]["1"]["failures"]


def test_restart_between_samples_cannot_be_hidden_by_recovered_counters():
    report = evaluate([camera(10), camera(1), camera(20)])
    assert "daemon_or_counter_reset" in report["cameras"]["1"]["failures"]


def test_stuck_publication_is_rejected_even_if_detector_keeps_running():
    first, last = camera(1), camera(2)
    last["telemetry"]["sequence"] = first["telemetry"]["sequence"]
    assert "output_not_progressing" in evaluate([first, last])["cameras"]["1"]["failures"]


def test_invalid_preview_is_rejected():
    report = hardware.evaluate_samples([{"cameras": [camera(1)]}, {"cameras": [camera(2)]}],
                                       1, {"1": {"decoded": False}})
    assert "invalid_preview_jpeg" in report["cameras"]["1"]["failures"]


def test_latest_only_drops_are_reported_without_failing_correct_output():
    first, last = camera(1), camera(2)
    last["counters"]["result_queue_drops"] = 5
    report = evaluate([first, last])
    assert report["passed"]
    assert "result_queue_drops" in report["cameras"]["1"]["warnings"]


@pytest.mark.parametrize("samples,elapsed", [([], 1), ([{"cameras": []}], 1),
                                             ([{"cameras": []}] * 2, 0)])
def test_insufficient_evidence_cannot_pass(samples, elapsed):
    with pytest.raises(ValueError):
        hardware.evaluate_samples(samples, elapsed, {})


def test_empty_camera_set_cannot_pass():
    with pytest.raises(ValueError, match="no enabled cameras"):
        hardware.evaluate_samples([{"cameras": []}] * 2, 1, {})


def test_cli_connection_failure_returns_error(monkeypatch, capsys):
    def unavailable(*args, **kwargs):
        raise OSError("Jetson unavailable")

    monkeypatch.setattr(hardware, "verify", unavailable)
    assert hardware.main([]) == 2
    assert not json.loads(capsys.readouterr().out)["passed"]


@pytest.mark.parametrize("scenario", ["healthy", "not_ready", "bad_jpeg"])
def test_verifier_collects_get_only_evidence_and_saves_report(monkeypatch, tmp_path, scenario):
    clock = iter([0., 0., .5, 1., 1.])
    sleeps, requests = [], []
    monkeypatch.setattr(hardware, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=sleeps.append))
    dashboards = 0
    jpeg = cv2.imencode(".jpg", np.zeros((8, 16), np.uint8))[1].tobytes()

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return self.body

    def get(url, timeout):
        nonlocal dashboards
        requests.append(url)
        assert timeout == 10
        if url.endswith("/healthz"):
            body = json.dumps({"ready": scenario != "not_ready"}).encode()
        elif url.endswith("/api/session/status"):
            body = b'{"session_id":null,"cameras":{}}'
        elif url.endswith("/api/dashboard"):
            dashboards += 1
            body = json.dumps({"cameras": [camera(dashboards)]}).encode()
        else:
            assert url.endswith("/api/camera/1/frame.jpg")
            body = b"bad jpeg" if scenario == "bad_jpeg" else jpeg
        return Response(body)

    monkeypatch.setattr(hardware, "urlopen", get)
    report = hardware.verify("http://jetson/", duration_s=1, interval_s=.5,
                             expected_cameras=["1"], expected_ids=[4], output_dir=tmp_path)
    assert report["passed"] == (scenario == "healthy")
    assert sleeps == [.5, .5] and len(requests) == 6
    assert json.loads((tmp_path / "report.json").read_text()) == report
    assert len(json.loads((tmp_path / "samples.json").read_text())) == 3
    assert (tmp_path / "camera-1.jpg").read_bytes() == (b"bad jpeg" if scenario == "bad_jpeg" else jpeg)


@pytest.mark.parametrize("duration,interval", [(0, 1), (1, 0), (1, 2)])
def test_verifier_rejects_invalid_sample_duration_before_network_access(duration, interval):
    with pytest.raises(ValueError):
        hardware.verify("http://unused", duration_s=duration, interval_s=interval)
