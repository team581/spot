# Test robot Pose3d with all four camera feeds

Run this from a terminal on the Mac, starting in the Spot repository. The Orin's last verified Ethernet address was `192.168.69.170`; override it with `--host team581@<new-address>` if it changes. Have a printed **2026 REBUILT AprilTag** with an ID in `config/2026-rebuilt-welded.json` ready.

## Start the camera grid and pose publisher

Launch the temporary viewer daemon and terminal dashboard with one command:

```sh
python3 tools/probe_dashboard.py --alpha
```

The command uses the existing checkout at `/home/team581/spot-2026` on the Orin; it does not copy Mac changes. For the direct Ethernet setup, it temporarily assigns the Mac `192.168.69.171/24` if the active adapter has only a self-assigned address, then removes that address on exit. Enter the Mac administrator password if `sudo` asks. SSH may separately ask for the Jetson account password, and remote `sudo` may ask again before the dashboard opens. If more than one active direct Ethernet adapter is found, use `--alpha-interface enX`. The command checks the installed service, stops it if it is running, and launches the complete alpha pose publisher with the camera and calibration interface. Keep the terminal open. The ChArUco wizard should open [http://192.168.69.170:8765/](http://192.168.69.170:8765/) in a browser; its `/viewer` link opens the read-only four-camera grid. Both pages use frames already owned by the pose publisher, so calibration does not open the USB devices a second time. Configured image rotations apply at capture to the viewer, detector, pose solver, and calibration. The replacement Swift camera currently uses 0 degrees after flipping its previously corrected feed. Open the URL manually if it does not appear. The previews are available only while this temporary daemon runs. Use `--host`, `--remote-dir`, `--remote-python`, or `--stream-host` to override the other documented defaults.

## Watch the poses in AdvantageScope

1. In AdvantageScope, choose **File → Connect to Robot → NetworkTables 4** and enter `192.168.69.170` if prompted. The dashboard displays the current NT4 address when `--host` is overridden.
2. Open a **3D Field** tab and select **2026 Field**. Expand **Spot → 1 → output** through **Spot → 4 → output**.
3. Add each `robot_pose` (`Pose3d`) topic to the field's **Poses** section. Watch the matching `robot_pose_valid`, `robot_pose_method`, `robot_pose_tag_count`, and `robot_pose_reprojection_error_px` topics in the sidebar. Arrange the browser camera grid beside AdvantageScope. If a pose cannot be added yet, show a known tag first so the topic receives its first sample.
4. Aim each camera at one known tag, then at two known tags visible in the **same camera frame**. For that camera, expect `robot_pose_valid=true`, a moving field pose, and a method change from `SINGLE_TAG_IPPE_SQUARE` with count `1` to `MULTI_TAG_SQPNP` with count `2` or more. Each camera has its own pose topic and emits one selected robot pose per solvable frame.

If `robot_pose_valid=false`, first check the matching camera tile: the last hardware check showed the left camera pointed at wiring/ceiling and the right camera facing a close obstruction. Clear the view, check the printed tag ID and lighting, and look at `/Spot/<camera>/status/state` and `/Spot/<camera>/status/error`. With no usable tag, Spot leaves the last pose untouched and publishes `valid=false`; it does not publish an origin pose. The shipped camera calibration and mount transforms are provisional, so this test checks the output path and behavior, not measured pose accuracy.

For a meaningful position on the field image, place the tag at its official field location and orientation. A loose printed tag can test detection and publishing, but its displayed field position will not match the room.

### Check the printed pattern orientation

Compare the black-and-white pattern to the corresponding page in
[FIRST's 2026 AprilTag Images and User Guide](https://firstfrc.blob.core.windows.net/frc2026/FieldAssets/2026-apriltag-images-user-guide.pdf).
The ID label can be upright while the pattern itself is inverted. ArUco's
generated tag36h11 images are 180° from FIRST's printed orientation. An inverted
wall tag interpreted with the official upright field layout makes an upright
camera appear upside down, mirrors its height about the tag center, and reverses
its pitch motion. Rotate the paper 180° or use a measured test layout that
includes the tag's actual roll; keep the official competition layout intact.

In the dashboard, **blue is the selected camera pose** (lowest reprojection
error), and **orange is the alternate single-tag solution**. Both are camera
poses, before applying the configured robot mount. The alternate can have
mirrored motion even with a correctly oriented tag. The table shows each
candidate's roll, pitch, yaw, and error; the stalk on the camera box marks its
up direction. Positive WPILib pitch points the camera down. Tilting a camera
down at a fixed position should move the tag up in the image while its estimated
height stays approximately constant. Two tags visible to the same camera help
resolve planar ambiguity.

## Finish

Press `q` in the dashboard terminal (or Ctrl-C). The command stops the temporary daemon and restores the installed service if it was running before the test. If the service was already stopped, it remains stopped. A restoration failure is printed in the terminal and makes the command exit with an error.

The temporary viewer is unauthenticated and intended only for a trusted local network. The installed service continues to publish NT4 poses after restart, but does not serve camera feeds.
