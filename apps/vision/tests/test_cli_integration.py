"""Exercise the image-regression command with real images."""

import json
from pathlib import Path

import pytest

from spot_vision import cli
from spot_vision.regression import run_image_regression

DATA = Path(__file__).parent / "data/regression"


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


@pytest.mark.parametrize("repeats,backend", [(0, "cpu"), (-1, "cpu"), (1, "magic")])
def test_regression_api_validates_arguments_before_loading_manifest(repeats, backend):
    with pytest.raises(ValueError):
        run_image_regression("does-not-exist", repeats=repeats, backend=backend)


def test_regression_api_rejects_empty_corpus(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"config": str((DATA / "config.json").resolve()), "cases": []}))
    with pytest.raises(ValueError, match="at least one case"):
        run_image_regression(manifest)
