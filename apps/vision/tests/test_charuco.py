from __future__ import annotations

import json

import pytest

from spot_vision.calibration_session import CameraSession
from spot_vision.charuco import CalibrationOptions, CharucoBoardConfig, calibrate, write_calibration


def test_board_and_options_reject_unsafe_values():
    with pytest.raises(ValueError):
        CharucoBoardConfig(square_length_m=0.03, marker_length_m=0.03).validate()
    with pytest.raises(ValueError):
        CalibrationOptions(model="fisheye").validate()


def test_empty_calibration_reports_progress_gate():
    result, report = calibrate([], CharucoBoardConfig(), CalibrationOptions())
    assert result is None
    assert not report.accepted
    assert report.frames_used == 0


def test_write_calibration_is_valid_json(tmp_path):
    target = tmp_path / "nested" / "calibration.json"
    write_calibration(target, {"schema_version": 2, "method": "charuco"})
    assert json.loads(target.read_text())["schema_version"] == 2
    assert not list(target.parent.glob("*.tmp*"))


def sample(points=None, ids=None):
    import numpy as np

    from spot_vision.charuco import CharucoFrame

    points = np.array(
        points if points is not None else [[100, 100], [130, 100], [100, 130], [130, 130]],
        dtype=float,
    )
    return CharucoFrame(
        points, np.array(ids if ids is not None else [0, 1, 2, 3]), (640, 480), 4, 0.4, 200, 0.8
    )


def test_auto_capture_compares_matching_corners_to_last_accepted_view():
    camera = CameraSession("1")
    options = CalibrationOptions()
    frame = sample()
    camera.last_detection = frame
    assert camera.accept(options, automatic=True)
    assert not camera.accept(options, automatic=True)
    assert len(camera.samples) == 1
    # Newly visible corners and changed ID ordering must not count as motion.
    frame = sample([[130, 130], [100, 130], [130, 100], [100, 100], [400, 400]], [3, 2, 1, 0, 4])
    camera.last_detection = frame
    assert not camera.accept(options, automatic=True)
    assert len(camera.samples) == 1
    # Movement accumulates relative to the saved frame, not each preview.
    frame = sample(sample().image_points + 10)
    camera.last_detection = frame
    assert not camera.accept(options, automatic=True)
    assert len(camera.samples) == 1
    frame = sample(sample().image_points + 20)
    camera.last_detection = frame
    assert camera.accept(options, automatic=True)
    assert len(camera.samples) == 2
    camera.last_detection = None
    assert not camera.accept(options, automatic=True)
    assert len(camera.samples) == 2


def test_auto_capture_accepts_scale_rotation_and_disjoint_board_regions():
    import numpy as np

    from spot_vision.calibration_session import frame_motion

    previous = sample([[100, 100], [400, 100], [100, 400], [400, 400]])
    center = previous.image_points.mean(axis=0)
    scaled = sample(center + (previous.image_points - center) * 1.2)
    rotated = sample(center + (previous.image_points - center) @ np.array([[0, -1], [1, 0]]))
    assert frame_motion(scaled, previous) > 0.025
    assert frame_motion(rotated, previous) > 0.025
    assert frame_motion(sample(ids=[10, 11, 12, 13]), previous) > 0.025


def test_coverage_tracks_accepted_views_and_capture_limit():
    camera = CameraSession("1")
    options = CalibrationOptions(min_frames=3, max_frames=3)
    camera.last_detection = sample([[50, 50], [80, 50], [50, 80], [80, 80]])
    for _ in range(3):
        assert camera.accept(options)
    assert not camera.accept(options)
    state = camera.coverage(CharucoBoardConfig())
    assert state["coverage_particles"]
    assert state["coverage_progress"] == 0
    assert state["coverage_good_fraction"] == 0
    assert len(camera.samples) == 3


def test_team_board_default_detects_all_rows_and_rejects_small_dictionary():
    from spot_vision.charuco import detect_frame, make_board

    config = CharucoBoardConfig()
    assert (
        config.squares_x,
        config.squares_y,
        config.square_length_m,
        config.marker_length_m,
        config.dictionary,
    ) == (15, 15, 0.030, 0.022, "DICT_4X4_250")
    board = make_board(config)
    image = board.generateImage((1200, 1200), marginSize=40)
    frame = detect_frame(image, config, CalibrationOptions())
    assert frame is not None
    assert frame.marker_count == 112
    assert len(frame.ids) == 196
    assert set(frame.ids // 14) == set(range(14))
    for dictionary in ("DICT_4X4_50", "DICT_4X4_100"):
        with pytest.raises(ValueError, match="needs 112 unique markers"):
            make_board(CharucoBoardConfig(dictionary=dictionary))


def projected_board(scale=25, skew=0, shift=0, angle=0, ids=None):
    import numpy as np

    from spot_vision.charuco import CharucoFrame

    ids = np.arange(196) if ids is None else np.asarray(ids)
    board_points = np.column_stack((ids % 14 + 1, ids // 14 + 1)) - 7.5
    transform = np.array([[scale, scale * skew], [0, scale]])
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    image_points = board_points @ transform.T @ rotation.T + [500 + shift, 500]
    return CharucoFrame(image_points, ids, (1000, 1000), 20)


def test_coverage_empty_duplicates_translation_roll_and_scale_only():
    import numpy as np

    from spot_vision.calibration_session import coverage_state

    board = CharucoBoardConfig()
    empty = coverage_state([], board)
    assert empty["coverage_particles"] == [] and empty["coverage_progress"] == 0
    single = coverage_state([projected_board()], board)
    repeated = coverage_state([projected_board()] * 30, board)
    assert repeated == single
    assert single["coverage_particles"] and single["coverage_good_fraction"] == 0
    for frames in (
        [projected_board(shift=i * 3) for i in range(20)],
        [projected_board(angle=i * 0.1) for i in range(20)],
        [projected_board(scale=i) for i in range(20, 50)],
        [projected_board(skew=i * 0.1) for i in range(10)],
    ):
        result = coverage_state(frames, board)
        assert result["coverage_good_fraction"] == 0
        assert result["coverage_progress"] < 0.001
    # Corner localization jitter does not earn independent-view credit.
    rng = np.random.default_rng(42)
    frames = [projected_board() for _ in range(20)]
    for frame in frames:
        frame.image_points += rng.normal(0, 0.25, frame.image_points.shape)
    assert coverage_state(frames, board)["coverage_good_fraction"] == 0


def test_coverage_requires_local_variety_and_does_not_reward_cropping():
    import numpy as np

    from spot_vision.calibration_session import _view_signature, coverage_state

    board = CharucoBoardConfig()
    assert np.allclose(
        _view_signature(projected_board(), board),
        _view_signature(projected_board(ids=np.arange(60)), board),
        atol=1e-5,
    )
    frames = [projected_board(scale=20 + i * 4, skew=i * 0.15) for i in range(8)]
    result = coverage_state(frames, board)
    assert 0 < result["coverage_good_fraction"] < 1
    assert any(p["progress"] == 1 for p in result["coverage_particles"])
    assert result["coverage_grid"][0][0] == 0
    assert any(p["progress"] < 1 for p in result["coverage_particles"])
    assert coverage_state(frames * 3, board) == result
    assert coverage_state(frames[:3], board)["coverage_good_fraction"] == 0


def test_auto_capture_skips_over_90_percent_green_but_allows_manual(monkeypatch):
    import numpy as np

    camera = CameraSession("1")
    board, options = CharucoBoardConfig(), CalibrationOptions()
    grid = np.ones((12, 12))
    grid[0, 0] = 0
    monkeypatch.setattr(camera, "coverage", lambda _: {"coverage_grid": grid.tolist()})
    points = [[300, 300]] * 10 + [[1, 1]]
    camera.last_detection = sample(points, list(range(11)))
    assert not camera.accept(options, automatic=True, board=board)
    assert not camera.samples and "Already green" in camera.capture_reason
    camera.last_detection = sample([[300, 300]] * 9 + [[1, 1]], list(range(10)))
    assert camera.accept(options, automatic=True, board=board)
    camera.last_detection = sample(points, list(range(11)))
    assert camera.accept(options)
