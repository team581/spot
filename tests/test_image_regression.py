"""Exercise production native geometry and the fixed-image end-to-end pipeline."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from spot_vision.config import load_calibration
from spot_vision.regression import run_image_regression

DATA = Path(__file__).parent / 'data' / 'regression'


@pytest.fixture
def native():
    from spot_vision import _spot_cuda
    if not hasattr(_spot_cuda, 'CpuDetector'):
        pytest.fail('build the native CPU module with SPOT_BUILD_CUDA=OFF to run image regressions')
    return _spot_cuda


def lens(native):
    calibration = load_calibration(DATA / 'calibration.json')
    k, d = native.CameraMatrix(), native.DistortionCoefficients()
    k.fx, k.fy = calibration.camera_matrix[0][0], calibration.camera_matrix[1][1]
    k.cx, k.cy = calibration.camera_matrix[0][2], calibration.camera_matrix[1][2]
    d.k1, d.k2, d.p1, d.p2, d.k3 = calibration.distortion
    return calibration, k, d


def test_native_undistortion_round_trip_and_opencv_oracle(native):
    calibration, k, d = lens(native)
    ideal = np.array([[640, 400], [100, 100], [1150, 700], [1050, 220]], dtype=float)
    normalized = np.column_stack(((ideal - [k.cx, k.cy]) / [k.fx, k.fy], np.ones(4)))
    raw = cv2.projectPoints(normalized, np.zeros(3), np.zeros(3),
                           np.asarray(calibration.camera_matrix),
                           np.asarray(calibration.distortion))[0].reshape(-1, 2)
    recovered = native.undistort_points(raw.tolist(), k, d)
    assert np.allclose(recovered, ideal, atol=1e-5)
    # Exercise p2 independently: the imported inverse had a k3 term here instead of 2*x*x.
    d.k1 = d.k2 = d.k3 = d.p1 = 0.
    d.p2 = 0.03
    raw = cv2.projectPoints(normalized, np.zeros(3), np.zeros(3),
        np.asarray(calibration.camera_matrix), np.array([0.,0.,0.,0.03,0.]))[0].reshape(-1, 2)
    assert np.allclose(native.undistort_points(raw.tolist(), k, d), ideal, atol=1e-5)
    with pytest.raises(ValueError):
        native.undistort_points([[float('nan'), 0.]], k, d)
    k.fx = 0.
    with pytest.raises(ValueError):
        native.undistort_points([[100., 100.]], k, d)


def test_edge_refinement_on_distorted_static_image_is_better_than_raw_line_fit(native):
    _, k, d = lens(native)
    image = cv2.imread(str(DATA / 'periphery.png'))
    frame = cv2.cvtColor(image, cv2.COLOR_BGR2YUV_YUY2)
    manifest = json.loads((DATA / 'manifest.json').read_text())
    truth = np.array(manifest['cases'][1]['tags'][0]['corners'])
    # Quad winding differs from canonical decoded tag order.
    quad = truth[::-1]
    rough = quad + np.array([[1., -1.], [-1., -1.], [-1., 1.], [1., 1.]])
    refined = np.array(native.refine_corners(frame, rough.tolist(), k, d))
    raw_fit = np.array(native.refine_corners(frame, rough.tolist(), k,
                                            native.DistortionCoefficients()))
    error = np.linalg.norm(refined - quad, axis=1).mean()
    raw_error = np.linalg.norm(raw_fit - quad, axis=1).mean()
    assert error < 1.5
    assert error < raw_error
    # Flat image and degenerate geometry must retain finite original corners.
    blank = np.full_like(frame, 128)
    assert np.allclose(native.refine_corners(blank, rough.tolist(), k, d), rough)
    degenerate = [[200., 200.]] * 4
    assert np.allclose(native.refine_corners(frame, degenerate, k, d), degenerate)


def test_static_images_capture_detection_pose_and_transport(native, tmp_path):
    report = run_image_regression(DATA / 'manifest.json', repeats=2)
    (tmp_path / 'metrics.json').write_text(json.dumps(report, indent=2))
    assert report['passed'], report
    assert len(report['cases']) == 5
    for case in report['cases']:
        assert case['timing_ms']['pipeline_mean'] > 0
        assert case['timing_ms']['detect_mean'] > 0


def test_regression_reports_accuracy_failure(native, tmp_path):
    manifest = json.loads((DATA / 'manifest.json').read_text())
    manifest['config'] = str(DATA.resolve() / 'config.json')
    manifest['cases'] = [manifest['cases'][0]]
    manifest['cases'][0]['image'] = str(DATA.resolve() / 'center.png')
    manifest['cases'][0]['max_corner_error_px'] = 0.00001
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    report = run_image_regression(path, repeats=1)
    assert not report['passed']
    assert 'corner_error' in report['cases'][0]['failures']
