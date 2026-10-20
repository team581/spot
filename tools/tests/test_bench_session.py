import importlib.util
import json
from pathlib import Path

import tempfile
import unittest

spec = importlib.util.spec_from_file_location("bench_session", Path(__file__).resolve().parents[1] / "bench_session.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def manifest(**extra):
    return {"cameras": ["front"], "scenario": "static", "min_decision_fps": 1, **extra}


def trace(tmp_path, rows):
    path = tmp_path / "frames.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def frame(t, age=.02, decision="ACCEPTED", camera="front"):
    return {"camera": camera, "decision": decision, "capture_fpga_s": t-age,
            "consume_fpga_s" if decision == "BENCH_FUSED" else "decision_fpga_s": t,
            "processing_ms": 4}


class BenchSessionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp_path = Path(directory.name)

    def test_rejected_and_consumed_populations_remain_separate(self):
        tmp_path = self.tmp_path
        path = trace(tmp_path, [frame(10), frame(10.1, .03, "BENCH_FUSED"), frame(10.2, .04, "NO_TAGS")])
        result = bench.analyze(path, manifest(require_consumption=True))
        item = result["cameras"]["front"]
        assert item["delivered"] == 2 and item["consumed"] == 1
        assert item["accepted"] == 1 and item["decisions"]["NO_TAGS"] == 1
        self.assertAlmostEqual(item["consumption_age_ms"]["p95"], 30)
        assert not result["hardware_qualified"]


    def test_no_data_and_excessive_warmup_cannot_pass(self):
        tmp_path = self.tmp_path
        assert not bench.analyze(trace(tmp_path, []), manifest())["screening_passed"]
        assert not bench.analyze(trace(tmp_path, [frame(10), frame(10.1)]), manifest(), 100)["screening_passed"]


    def test_gaps_at_end_of_recording_are_not_hidden(self):
        tmp_path = self.tmp_path
        rows = [frame(10), frame(10.1), {"_kind": "telemetry", "_log_fpga_s": 12,
                                        "key": "Bench/LoopWorkMs", "value": 2}]
        result = bench.analyze(trace(tmp_path, rows), manifest())
        self.assertAlmostEqual(result["cameras"]["front"]["delivery_gap_ms"]["max"], 1900)
        assert any("gap" in s for s in result["review_required"])


    def test_unknown_missing_camera_and_future_frames_cannot_make_a_fast_pass(self):
        tmp_path = self.tmp_path
        rows = [frame(10, -.02), frame(10.1, -.02), frame(10.2, camera="other")]
        result = bench.analyze(trace(tmp_path, rows), manifest(cameras=["front", "back"]))
        assert result["cameras"]["front"]["invalid_age_count"] == 2
        assert result["cameras"]["front"]["decision_age_ms"]["n"] == 0
        assert any("back: no delivered" in s for s in result["review_required"])
        assert not result["screening_passed"]


    def test_malformed_rows_and_short_recording_flag_review(self):
        tmp_path = self.tmp_path
        path = trace(tmp_path, [frame(10), frame(10.1), {"no": "timestamp"}])
        with path.open("a") as f:
            f.write("{broken\n")
        result = bench.analyze(path, manifest(), duration_s=30)
        assert result["malformed_rows"] == 2
        assert any("duration" in s for s in result["review_required"])


    def test_comparison_rejects_regressions_and_does_not_silently_change_scenarios(self):
        tmp_path = self.tmp_path
        base = bench.analyze(trace(tmp_path, [frame(10+i/30) for i in range(90)]), manifest())
        candidate = bench.analyze(trace(tmp_path, [frame(10+i/30, .03) for i in range(90)]), manifest())
        assert bench.compare(base, candidate)["recommendation"] == "reject_candidate"
        candidate["manifest"] = manifest(scenario="rotation")
        assert bench.compare(base, candidate)["recommendation"] == "inconclusive"
        assert bench.compare(base, base)["recommendation"] == "repeat_candidate"


    def test_doctor_handles_no_status_and_explains_unsupported_mode(self):
        tmp_path = self.tmp_path
        path = trace(tmp_path, [{"error": "connection refused"}])
        assert "No successful" in bench.doctor(path)["issues"][0]
        path = trace(tmp_path, [{"status": {"connected": False, "clock": {"state": "Unknown"},
            "lock_reason": "Unknown robot state", "cameras": [{"name": "front",
            "allowed_modes": [{"id": "capture-30", "supported": False}]}]}}])
        report = bench.doctor(path)
        assert len(report["issues"]) == 4
        assert any("capture request is not advertised" in s for s in report["issues"])


    def test_nonzero_logger_errors_are_visible(self):
        tmp_path = self.tmp_path
        rows = [frame(10+i/30) for i in range(90)]
        rows.append({"_kind": "telemetry", "_log_fpga_s": 11, "key": "Bench/LoggingErrors", "value": 2})
        result = bench.analyze(trace(tmp_path, rows), manifest())
        assert any("Bench/LoggingErrors" in s for s in result["review_required"])
