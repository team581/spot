# Spot v1 proposal

## Differences from Madtown proof-of-concept

- This is a rewrite, not a port, of the original Python system ran at Madtown
- Goals are to improve robustness and usability by heavily simplifying the feature set of the original system
- Only the vision service, dashboard, and tooling are rewritten
  - The Nix flake, J401 hardware module, installer ISO, and deploy flow carry over as-is

## Non-goals

- CSI cameras, YUYV/raw formats
- Cross-camera fusion or temporal filtering on the backend
- Dynamic robot→Spot tag selection
- More than one Spot per robot
- Authentication or access control of any kind
- Support bundle, diagnostics recording
- Calibration history, holdout validation, rational distortion model
- Re-running the pipeline on recorded MCAP (deferred until needed)

## Hardware

- Seeed Studio reComputer J401 - Open-source carrier board for Jetson Orin Nano 8GB
  - Same as original system
  - Coin cell battery for the RTC
- [Swyft USB camera](https://swyftrobotics.com/electrical/swyft-usb-camera)
  - OV9281 global shutter, mono, USB 2.0 UVC, MJPEG only, 1280×800 @ 120 FPS

## OS

- NixOS used to configure Jetson for declarative, deterministic environments
- systemd notify service with watchdog
- mDNS `spot.local` plus a fixed maintenance address

## Vision service

- Monolithic vision service which handles processing camera feeds, estimating poses, publishing data to robot, and serving a web dashboard
  - Rust, with C/C++ only in thin FFI shims (detector, hardware APIs)
- Serves dashboard static files and HTTP API directly (no NGINX)
- Never crashes on bad input
  - Invalid config is rejected, last good config keeps running, error is reported
  - Disconnected cameras are retried with backoff

### Cameras

- USB UVC via V4L2, MJPEG only, decoded on the NVJPG hardware engine
- Each configured camera specifies exactly one of `serial` or `port`
  - Serial is preferred, cameras can be reflashed with unique serials
  - A serial matching multiple devices is a camera error, never a guess
  - Port labels (ex. `usb1`) are defined in the Nix J401 module to match physical ports
- Exposed controls: mode (resolution + FPS), `auto_exposure` (manual / aperture priority), `exposure_time_absolute`, `gain`
  - Everything else is left at camera defaults
- Frames timestamped with kernel V4L2 buffer timestamps, converted to NT server time
  - No per-camera latency knobs
- Capture and detection run independently per camera, latest frame wins
  - Falling behind drops frames (counted in camera status) instead of adding latency

### AprilTag detection

- Our own detector (`apps/vision/src/apriltag`) combining concepts from NAPA and the 971 CUDA detector
  - Dense stage (sparse sample pyramid, local contrast and noise thresholds, dark-sample bitmask) runs on the GPU, straight from NVJPG output
  - Blob grouping, edge fitting, and decoding run on the CPU, only for tag-shaped candidates
  - Edges are fit in undistorted space when the camera is calibrated
  - `spot-vision corpus` scores accuracy and speed on labelled frames
- tag36h11 only

### Pose estimation

- Stateless: at most one estimate per camera per frame
- Full 6-DOF robot pose (x, y, z, roll, pitch, yaw), seeded from a flat-on-the-floor sweep
  - Soft prior toward flat on the floor (σ 0.1 m height, 5° roll/pitch), so far tags can't pick a physically impossible pose; tags that clearly show a tilt still win
  - Fits all visible tags at once using the robot-to-camera mount
  - Returns a primary and optional alternate candidate, robot disambiguates (ex. by heading)
- Backend only rejects tags that are unknown, listed in `ignored_tags`, or seen by an uncalibrated camera
  - All trust decisions belong to robot code

### Calibration

- ChArUco, run on the Jetson, guided from the dashboard
  - Live board detection with a coverage hint
  - Minimum frame count, one MAD outlier rejection refit pass, RMS threshold
- OpenCV 5 coefficient distortion model
- Board geometry is configurable, dashboard generates a printable board
- Results become a dashboard override, which is copied into the robot TOML
  - Keyed by camera name + resolution

### Web dashboard

- Static site written in TypeScript + React
- Docs via Astro, also embedded in the dashboard
- HTTP API described by OpenAPI generated from Rust types, with a generated TypeScript client
- Live camera views use the Foxglove SDK's WebSocket server (see [Recording](#recording))
- Bring-up needs no other tools: the dashboard covers tuning, calibration, mount checks, and recording review
- Pages
  - Camera grid with tag overlays
  - 3D field view
    - Field tags, each camera's robot estimate, the camera on that robot, lines drawn to tags
  - Camera detail: mode, exposure, gain, detections table
  - Camera naming (assign port/serial to a camera name)
  - Calibration
  - Config: overrides diff against robot config, copy merged TOML, paste TOML to replace it as overrides
  - Network: team number, DHCP/static IP, NT server override
    - Changes are applied by a root helper with trial → confirm → automatic rollback
  - System: CPU, GPU, temperature, per-camera FPS
  - Recordings
    - Download as MCAP
    - Replay in the browser (3D field view + camera images with overlays)
  - Docs

## Robot integration

### Config

- Robot code loads TOML config as a string and exposes it via NT
  - Spot backend reads the config and uses that
  - JSON Schema published at <https://spot.frc581.com/> for editor validation
  - Includes cameras (name, `serial`/`port`, `required`, mode, controls, mount, calibrations), `ignored_tags`
- Last robot config is cached on the Jetson for bench use without a robot
- Team number, IP, and NT server are Jetson-local settings, not robot config
- Overrides can be made via dashboard
  - Persisted on the Jetson
  - Automatically pruned once robot config matches
  - Status reports when any override is active

### NetworkTables

- The backend should have no knowledge of robot, communication is almost exclusively unidirectional
- Lean into NT4 protocol for things like timestamping data, avoid introducing new primitives & bloating the Spot↔robot protocol
- NT4 client named `spot`, values are WPILib structs with published schemas
- Each value's NT timestamp is the frame capture time in NT server time
  - Robot code passes it directly to `addVisionMeasurement`, no separate latency field
- Nothing is published until NT time sync is acquired

| Topic                                   | Direction  | Type   | Contents                                           |
| --------------------------------------- | ---------- | ------ | -------------------------------------------------- |
| `/Spot/inputs/config`                   | Robot→Spot | string | TOML config                                        |
| `/Spot/inputs/fieldLayout`              | Robot→Spot | string | WPILib `AprilTagFieldLayout` JSON                  |
| `/Spot/outputs/status`                  | Spot→Robot | struct | Version, state enum, overrides active              |
| `/Spot/outputs/error`                   | Spot→Robot | string | Details for the current non-ready state            |
| `/Spot/outputs/cameras/<name>/estimate` | Spot→Robot | struct | Pose estimate, only published for frames with tags |
| `/Spot/outputs/cameras/<name>/status`   | Spot→Robot | struct | State enum, FPS, dropped frames                    |

- Estimate struct
  - Primary `Pose3d` + reprojection error
  - Optional alternate `Pose3d` + reprojection error
  - Observed tag ID bitmask (`int64`, IDs 0-63)
  - Average tag distance, total tag image area fraction
- State enums report the most fundamental problem, with details in `outputs/error`
  - Spot: `ready`, `waiting_for_time_sync`, `waiting_for_config`, `invalid_config`, `missing_camera`, `uncalibrated_camera`
    - Only cameras marked `required` affect Spot state
  - Camera: `streaming`, `disconnected`, `duplicate_serial`, `uncalibrated`, `falling_behind`
- Spot also reads the standard `/FMSInfo` table for recording triggers

### Client library

- Java vendordep in `packages/java-client`
- Struct definitions, publishes config + field layout, per-camera estimate callbacks
  - Expands the tag ID bitmask into an `int[]`
- No trust policy, that stays in robot code

## Recording

- MCAP via the Foxglove Rust SDK
  - The same log calls feed the dashboard's live views over the SDK's WebSocket server
  - Replayed in the dashboard
- Contents
  - Per-camera passthrough JPEGs, capped at 30 FPS
  - Tag detections (corners, IDs) and estimates at full rate
  - Camera status, effective config and field layout (at start and on every change), service logs
- Merged recordings put everything but images first, in their own chunks, so replay loads them without reading images
- Rolling on-disk buffer of short segments, long enough for the pre-enable lead-in
  - Segments from ~5 s before enable to ~5 s after disable are kept as a recording, based on `FMSControlData` (works with a Driver Station alone)
  - Named by event + match when FMS is attached, otherwise by time
  - Oldest recordings deleted above 80% disk usage
- Log time is NT server time, the same time base as WPILOG
  - Wall clock only used for filenames and metadata

## Tooling

- `vscode-camera-preview` rewritten from scratch, reads the TOML config
