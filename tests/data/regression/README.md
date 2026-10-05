# Fixed image regression fixtures

`generate.py` produces these tag36h11 PNGs and the manifest with independent
OpenCV projections, without importing Spot's geometry or pose helpers. The
field scene has two tags facing +X; the camera is at (2, 0, 0.6) m looking -X.
Physical tag size is 0.3 m. The camera uses a five-coefficient Brown-Conrady lens
with both radial and tangential distortion. The peripheral tag measures about
46 pixels of distortion; the central tag measures about 0.2 pixels.

The manifest contains exact projected raw corners and expected robot translation
and quaternion, with pixel/metre/degree gates. The default mount is identity.
`config_rotated.json` describes raw sensor intrinsics rotated 180 degrees; its
image passes through the normal orientation correction to match the multi-tag
fixture. PNGs are checked in so running regressions does not depend on marker
generation or remapping changes in a future OpenCV version.

Regenerate intentionally using `python tests/data/regression/generate.py`.
Run `python -m spot_vision image-regression --manifest
 tests/data/regression/manifest.json --backend cpu --repeats 20 --output
 /tmp/spot-regression.json` as a single shell command. Repeat with `--backend cuda`
on the Orin; that path forbids fallback. The report includes timing measurements
without machine-dependent timing gates. This synthetic corpus complements the
upstream real JPEG detection tests and is not a substitute for measured real
camera/field accuracy or live camera throughput.

`official-tag4.png` is the unmodified 10×10 Tag 4 image from
[AprilRobotics](https://github.com/AprilRobotics/apriltag-imgs/blob/master/tag36h11/tag36_11_00004.png).
Its orientation matches Tag 4 in FIRST's 2026 AprilTag Images and User Guide.
`tests/test_pose_pitch.py` uses this independent artwork to exercise native
detection and pitch recovery. ArUco's generated tag36h11 patterns require a
180° rotation to match the official printed orientation; an upright ID label
alone does not establish the pattern's orientation.
