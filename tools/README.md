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
Red X points right, green Y points up, and blue Z points out of each tag. These
per-tag orientation estimates use active camera intrinsics even without a field layout.
The field map shows the published robot estimate and alternate camera candidates,
with position, heading, height, and reprojection error for manual pose verification.
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

With the repository's existing test environment:

```sh
.venv/bin/python -m pytest tools/tests tests
```

Dashboard tests use synthetic observations, a fake local SSH executable, and a
local pseudo-terminal. They never contact a host. Authentication, live remote
Ctrl-C cleanup, camera access, and performance remain Jetson acceptance checks.
