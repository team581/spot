"""Regenerate deterministic tag36h11 fixtures from an independent pinhole scene.

The oracle projects explicit field Y/Z corners with OpenCV; it does not import
Spot's pose/geometry helpers. PNGs and expected geometry are checked in.
"""

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
K = np.array([[700.0, 0, 640], [0, 700.0, 400], [0, 0, 1.0]])
D = np.array([-0.18, 0.04, 0.006, -0.008, 0.01])
SIZE = 0.3
# Camera looks along field -X; right is field +Y; down is field -Z.
R = np.array([[0.0, 1, 0], [0, 0, -1], [-1, 0, 0]])
CAMERA = np.array([2.0, 0.0, 0.6])
rvec = cv2.Rodrigues(R)[0]
tvec = -R @ CAMERA
layout = {1: [0.0, 0.0, 0.6], 2: [0.0, 1.35, 0.85]}
(ROOT / "layout.json").write_text(
    json.dumps(
        {
            "tags": [
                {
                    "ID": i,
                    "pose": {
                        "translation": dict(zip(("x", "y", "z"), xyz)),
                        "rotation": {"quaternion": {"W": 1.0, "X": 0.0, "Y": 0.0, "Z": 0.0}},
                    },
                }
                for i, xyz in layout.items()
            ]
        },
        indent=2,
    )
    + "\n"
)
(ROOT / "calibration.json").write_text(
    json.dumps(
        {
            "camera_id": "front",
            "width": 1280,
            "height": 800,
            "camera_matrix": K.tolist(),
            "distortion_coefficients": D.tolist(),
        },
        indent=2,
    )
    + "\n"
)
config = {
    "field_layout": "layout.json",
    "tag_size_m": SIZE,
    "cameras": [
        {
            "id": "front",
            "selector": {"device": "/dev/null"},
            "width": 1280,
            "height": 800,
            "fps": 60,
            "calibration": "calibration.json",
            "detector": {"backend": "cpu"},
            "robot_from_camera": {"translation_m": [0.0, 0.0, 0.6]},
        }
    ],
}
(ROOT / "config.json").write_text(json.dumps(config, indent=2) + "\n")
# Build inverse remap once: raw output pixels sample their ideal image locations.
pixels = np.indices((800, 1280))[::-1].transpose(1, 2, 0).astype(np.float64)
criteria = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-10)
if hasattr(cv2, "undistortPointsIter"):
    ideal = cv2.undistortPointsIter(pixels.reshape(-1, 1, 2), K, D, None, K, criteria)
else:
    ideal = cv2.undistortPoints(pixels.reshape(-1, 1, 2), K, D, P=K, criteria=criteria)
ideal = ideal.reshape(800, 1280, 2)
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
cases = []
for name, ids in [("center", [1]), ("periphery", [2]), ("multi", [1, 2]), ("blank", [])]:
    image = np.full((800, 1280), 255, dtype=np.uint8)
    expected = []
    for tag_id in ids:
        xyz = np.array(layout[tag_id])
        # AprilTag native corner order: bottom left, bottom right, top right, top left.
        offsets = np.array(
            [
                [0, -SIZE / 2, -SIZE / 2],
                [0, SIZE / 2, -SIZE / 2],
                [0, SIZE / 2, SIZE / 2],
                [0, -SIZE / 2, SIZE / 2],
            ]
        )
        objects = xyz + offsets
        corners = cv2.projectPoints(objects, rvec, tvec, K, D)[0].reshape(4, 2)
        flat = cv2.projectPoints(objects, rvec, tvec, K, np.zeros(5))[0].reshape(4, 2)
        # Rotate ArUco's pattern to match FIRST's printed tag orientation.
        # In that orientation the native detector starts at the bottom left.
        marker = cv2.rotate(cv2.aruco.generateImageMarker(dictionary, tag_id, 240), cv2.ROTATE_180)
        # The marker's outer black border is the physical tag boundary.
        h = cv2.getPerspectiveTransform(
            np.array([[0, 0], [240, 0], [240, 240], [0, 240]], np.float32),
            flat[[3, 2, 1, 0]].astype(np.float32),
        )
        projected = cv2.warpPerspective(marker, h, (1280, 800), borderValue=255)
        image = np.minimum(image, projected)
        expected.append({"id": tag_id, "corners": corners.tolist()})
    raw = cv2.remap(
        image,
        ideal[..., 0].astype(np.float32),
        ideal[..., 1].astype(np.float32),
        cv2.INTER_LINEAR,
        borderValue=255,
    )
    cv2.imwrite(str(ROOT / (name + ".png")), raw)
    cases.append(
        {
            "name": name,
            "image": name + ".png",
            "tags": expected,
            "robot_translation_m": [2.0, 0.0, 0.0] if ids else None,
            "robot_quaternion_wxyz": [0.0, 0.0, 0.0, 1.0] if ids else None,
            "max_rotation_error_deg": 10.0,
            "max_corner_error_px": 2.0,
            "max_translation_error_m": 0.15,
            "max_reprojection_error_px": 1.0,
        }
    )
# Raw sensor rotated 180 degrees, corrected back by the production replay path.
cv2.imwrite(
    str(ROOT / "rotated.png"), cv2.rotate(cv2.imread(str(ROOT / "multi.png")), cv2.ROTATE_180)
)
raw_K = K.copy()
raw_K[0, 2], raw_K[1, 2] = 1279 - K[0, 2], 799 - K[1, 2]
raw_D = D.copy()
raw_D[2:4] *= -1
(ROOT / "calibration_rotated.json").write_text(
    json.dumps(
        {
            "camera_id": "front",
            "width": 1280,
            "height": 800,
            "camera_matrix": raw_K.tolist(),
            "distortion_coefficients": raw_D.tolist(),
        },
        indent=2,
    )
    + "\n"
)
config["cameras"][0]["calibration"] = "calibration_rotated.json"
config["cameras"][0]["image_rotation_deg"] = 180
(ROOT / "config_rotated.json").write_text(json.dumps(config, indent=2) + "\n")
cases.append(dict(cases[2], name="rotated", image="rotated.png", config="config_rotated.json"))
(ROOT / "manifest.json").write_text(
    json.dumps({"config": "config.json", "camera": "front", "cases": cases}, indent=2) + "\n"
)
