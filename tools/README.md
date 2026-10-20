# Prototype terminal dashboard and alpha calibration GUI

This disposable development tool runs on your **laptop** and launches either Spot's
existing single-camera probe or a standalone multi-camera daemon over SSH. It is not
part of Spot's production package or deployment and has no authority over production
architecture, interfaces, filtering, or tuning. Removing `tools/`, the small optional
observer/debug-log seam in the service, and the `/prototype-runs/` ignore entry removes
the tooling. Nothing is installed into the Jetson's systemd service.

## Try locally

Use Python 3.10+ in a macOS or Linux terminal with curses support. No Spot package,
CUDA, or third-party Python packages are needed on the laptop.

```sh
python3 tools/probe_dashboard.py --demo
python3 tools/probe_dashboard.py --daemon --demo
```

The deterministic demo lasts about 15 seconds, includes disappearing tags and a
stale interval, and saves synthetic recordings. Press `q` or Ctrl-C to stop early.
The display refreshes four times per second and adapts to terminal size; enlarge
the terminal to see more rows and events. Redirected/noninteractive output is rejected.

## Live SSH usage — only when ready for a Jetson run

```sh
python3 tools/probe_dashboard.py \
  --host orin-1 \
  --remote-dir /actual/path/to/spot-2026 \
  --camera front
```

Replace the remote directory with your existing Jetson checkout. `--host` accepts
your usual SSH alias or `user@host`; ports, keys, and other settings come from your
SSH configuration. Normal password and host-key prompts appear **before** the
screen opens. The tool uses a private, temporary SSH control socket to reuse that
authenticated connection and closes its own connection on exit.

The remote command uses `.venv/bin/python -u -m spot_vision probe`, from the
specified checkout. `--remote-python` overrides that interpreter. `--config`
defaults to `config/spot.json`, relative to the remote checkout; absolute remote
paths also work. `--frames 100` stops after 100 processed frames (default: unlimited).
Use a path rather than `~` or shell expressions: arguments are quoted literally.

This launches a new probe; it does not attach to an existing one, deploy files,
change configuration, or stop a daemon. Ensure the camera is available to the
probe and your SSH account can access it. No live Jetson validation has been
performed as part of local implementation.

## Temporary alpha GUI

Stop any systemd or manually started Spot daemon that already owns the cameras,
then run:

```sh
python3 tools/probe_dashboard.py \
  --daemon \
  --host orin-1 \
  --remote-dir /actual/path/to/spot-2026
```

Daemon mode starts the complete configured service and the vision dashboard.
Open `http://<jetson-ip>:8765/` to view all cameras, calibration status, tag orientation,
and field pose; after the server
becomes healthy, the dashboard opens that URL in the local browser automatically.
The calibration tool is linked at `/calibration`; the simple multi-camera grid remains
available at `/viewer`. Use **Customize workspace** for side-by-side, stacked, or
feed-focused layouts, feed proportions and height, tile size, optional overview and
summary panels, and axis/candidate overlays. Preferences persist in this browser.
Freeze inspection holds the selected image and its matching pose while capture continues.
**Camera tuning** edits the selected camera's live V4L2 image controls. Refresh
reads supported controls, current values, ranges, steps, and menu options from the
device. Adjust a slider or numeric field and press its **Apply** button; the server
validates the request and reads the value back before reporting success. Exposure
is shown in microseconds (UVC absolute exposure uses 100 µs units). Manual exposure
and white balance are disabled while their automatic mode is enabled. Tuning is
disabled while inspection is frozen or the dashboard is disconnected.

The camera firmware determines which controls appear. The alpha Jetson reported
these differences on October 3, 2026:

| Control | Swift USB (camera 1) | Arducam OV9281 UC762 (cameras 2–4) |
| --- | --- | --- |
| Manual exposure | 5,000–1,000,000 µs, step 100 µs | 100–500,000 µs, step 100 µs |
| Gain | 1–128 | 0–100 |
| Black level / brightness | −64–64 | −64–64 |
| Contrast | 0–100 | 0–64 |
| Gamma | 100–500 | 72–500 |
| Sharpness | 0–100 | 0–6 |

All four advertise manual/automatic exposure, 50/60 Hz anti-flicker, backlight
compensation, saturation, hue, and automatic/manual white balance. Color controls
may have no effect on monochrome cameras. Values are firmware units unless labeled.
Brightness is the standard V4L2 black-level control; it is not sensor exposure.
The dashboard intentionally excludes trigger/dynamic-framerate and geometric
controls that could stop streaming or invalidate calibration. Arducam documents
`exposure_dynamic_framerate` as the OV9281 external-trigger switch.

Changes affect capture and detection immediately, use the existing capture owner,
and are replayed after camera reconnects for this process. They do not edit
`config/spot.json`: restarting alpha restores configured exposure and gain; other
controls can retain values in camera firmware. Refresh after another tool changes
camera settings. The per-process camera token guards writes against cross-origin
browser requests; this remains a trusted-LAN alpha interface.

Control references:
[Arducam OV9281 UVC operations](https://docs.arducam.com/UVC-Camera/Appilcation-Note/External-Trigger-Mode/OV9281-Global-Shutter/),
[Linux V4L2 image-control definitions](https://docs.kernel.org/userspace-api/media/v4l/control.html),
and [Linux V4L2 exposure units and modes](https://docs.kernel.org/userspace-api/media/v4l/ext-ctrls-camera.html).

Red X points right, green Y points up, and blue Z points out of each tag. These
per-tag orientation estimates use active camera intrinsics even without a field layout.
Pose verification uses a lightweight, offline 3D Canvas viewer of the 2026 REBUILT
field perimeter and simplified hubs. Drag or use arrow keys to orbit, scroll or use
+/− to zoom, and Reset view to restore the overview. The selected camera body and
view direction use its full field quaternion; observed tags are highlighted at their
configured positions and orientations. Tag markers are enlarged for visibility.
Camera and observed-tag X/Y/Z coordinates (meters) and yaw (degrees) appear below,
in the WPILib blue-origin frame: +X toward red, +Y left, +Z up. Robot X/Y and yaw
remain separate from the camera estimate. Stale estimates are hidden unless frozen.
Provisional calibration is clearly marked; saving new calibration requires an alpha
restart before pose output uses it. Disabled, waiting, and stale cameras stay visible. If an SSH alias is
not also browser-resolvable, pass
`--stream-host <jetson-ip>`. `--stream-port` changes port 8765, and
`--no-open-browser` prints the URL without opening it.
The configured `image_rotation_deg` is applied once at capture, before detection,
pose solving, and preview. The bundled alpha config sets the left mount to 180
degrees; the right mount uses the default 0 degrees. This setting belongs to the
logical camera mount, so replacing a camera or changing its USB port does not
change the orientation. The calibration file describes raw sensor pixels; Spot
transforms its intrinsics for the corrected frame. Configure `robot_from_camera`
for that corrected frame.

The server retains only the latest post-detection frame. The preview encoder produces grayscale images
at no more than 640×360, 15 FPS per camera, and JPEG quality 70, and stops encoding
when nobody is viewing. Tag-axis projection runs in the bounded preview worker,
and each inspection image carries the detections and pose from exactly that frame. It never opens cameras a second time and preview failures do
not stop the vision service.
The browser holds each camera's last decoded frame during a brief stream interruption
and resumes when a new frame arrives. Its status label reports when that image is stale.
The alpha web surface uses a per-process token for calibration changes, but it is
still intended only for a trusted LAN.
It is not enabled by systemd and is not a production interface. A camera that
has not produced a frame remains represented by a waiting tile.

## Display and recordings

The display shows current detections (including duplicate IDs), hamming, decision
margin, capture FPS, received-results rate, latest sequence, reported overwrites,
and timing statistics. At most 12 tag rows are displayed; all remain in the log.
A five-second rolling window holds at most 5,000 observations, and the event list
holds 20 entries. A fresh empty detection differs from waiting or stale data.
After two seconds without a result, displayed measurements are explicitly stale.

- **Capture FPS** is the probe's reported value.
- **Received rate** is measured at the laptop, affected by SSH and file-reader
  buffering and the bounded sample window. It is not detector throughput.
- **Probe processing time** measures the existing probe's detector-call duration;
  it excludes capture and publication. Detector time is reported separately.
- Overwrites use the probe's reported counter. Sequence gaps are not reclassified
  as hardware drops, and no production acceptance thresholds are inferred.

Each run creates a unique local directory in `prototype-runs/` (Git-ignored).
`--log-dir /path/to/recordings` changes the parent directory. `probe.log` contains
single-camera output; daemon mode uses `daemon.log`. Both retain every observation
with corners and remote diagnostics. `ssh.log` contains SSH-client diagnostics.
The probe demo uses the latter for its synthetic stderr message.
The terminal on the Jetson combines remote stdout and stderr, so this transcript
is not a pure JSONL file. Authentication prompts remain on the real terminal and
are not saved in these logs.

Output is written directly to disk and followed independently of rendering.
Display history is bounded; recording files grow for the duration of the run.
Malformed and oversized lines are retained on disk but omitted or summarized on
screen; control characters are sanitized for display. A connection failure cannot
recover remote results that never reached the laptop.

Pressing `q` or Ctrl-C sends Ctrl-C through the remote terminal, waits up to five
seconds, then closes SSH if needed. The local terminal is restored, and a session
summary and recording location are printed. Connection failures end the session
without reconnecting or starting another probe. Remote cleanup during real network
failure still requires live validation; do not assume remote shutdown is confirmed
when the connection is lost.

## Local verification

Run the HTTP and CPU packaging checks after building the Jetson docs:

```sh
mise run check:application
```

With the repository's full development environment, run all tests:

```sh
.venv/bin/python -m pytest tools/tests tests
```

Dashboard tests use synthetic observations, a fake local SSH executable, and a
local pseudo-terminal. They never contact a host. Authentication, live remote
Ctrl-C cleanup, camera access, and performance remain Jetson acceptance checks.

### Operator documentation

The guides in `docs-site/src/content/docs/` appear on both the Jetson at `/docs/` and the [Astro + Starlight](https://starlight.astro.build/) site in `docs-site/`.
Edit the shared guides to update both versions.

Run `pnpm --dir docs-site build:jetson` before building a Spot wheel. It produces `dist/jetson-docs/`, which is bundled into the installed application for offline use.


## Robot integration session

The [bench session guide](../docs-site/src/content/docs/operator/robot-integration-session.md) covers
separate MacBook–Jetson and Jetson–roboRIO Ethernet links, agent-configured
routing/relay access, setup/recovery checks, and an agent-owned execution/repair loop. `bench_capture.py` records bounded Jetson status alongside the running
service; `bench_session.py` creates run snapshots, collects explicit remote
paths, diagnoses status, and summarizes exported tester WPILOGs. Both use Python
3.10+ standard libraries. Run `--help` for commands. The agent executes setup, deployment, GUI checks, collection and retests;
requests for human help are limited to unavailable physical actions/access. Start
with setup failures; latency statistics are supporting evidence. Artifacts live in ignored
`bench-runs/`. Test the report logic with
`python3 -m unittest discover -s tools/tests -p test_bench_session.py`.
