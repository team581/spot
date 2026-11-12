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
- Offline MCAP replay (deferred until needed)

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

- Our own detector (`apps/vision/src/apriltag`), after NAPA's approach: full-resolution work only where tags are likely
  - Dense stage (sparse sample pyramid, local contrast and noise thresholds, dark-sample bitmask) runs on the GPU, straight from NVJPG output
    - A bit-identical CPU version runs it on dev machines
  - Blob grouping, edge fitting, and decoding run on the CPU, only for tag-shaped candidates
  - Edges are fit in undistorted space when the camera is calibrated
  - Detector only provides tag corners, pose solving is ours
  - Replaced the Team 766 / FRC 971 CUDA detector: 4-7x faster on the Orin Nano and finds more tags
- tag36h11 only

### Pose estimation

- Stateless: at most one estimate per camera per frame
- Full 6-DOF robot pose (x, y, z, roll, pitch, yaw), seeded from a flat-on-the-floor sweep
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
- Live camera views use the Foxglove WebSocket channels (see [Recording](#recording))
- Pages
  - Camera grid with tag overlays
  - Camera detail: mode, exposure, gain, detections table
  - Camera naming (assign port/serial to a camera name)
  - Calibration
  - Config: overrides diff against robot config, copy merged TOML
  - Network: team number, DHCP/static IP, NT server override
    - Changes are applied by a root helper with trial → confirm → automatic rollback
  - System: CPU, GPU, temperature, per-camera FPS
  - Recordings download
  - Docs

## Robot integration

### Config

- Robot code loads TOML config as a string and exposes it via NT
  - Spot backend reads the config and uses that
  - JSON Schema published at <https://spot.frc581.com/> for editor validation
  - Includes cameras (name, `serial`/`port`, `required`, mode, controls, mount, calibrations), tag size, `ignored_tags`, recording settings
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
| `/Spot/inputs/saveRecording`            | Robot→Spot | double | Optional, protect the last N seconds of recording  |
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

- Java library in the robot code monorepo for now, vendordep longer term
- Struct definitions, publishes config + field layout, per-camera estimate subscribers
  - Expands the tag ID bitmask into an `int[]`
- No trust policy, that stays in robot code

## Recording

- MCAP via the Foxglove Rust SDK
  - The same log calls feed a live Foxglove WebSocket server
  - Mount/pose debugging is done in Foxglove's 3D panel (camera transforms, field tags, estimates, annotated images)
- Contents
  - Per-camera passthrough JPEGs, FPS capped by config (default 30)
  - Tag detections (corners, IDs) and estimates at full rate
  - Camera status, effective config (at start and on every change), service logs
- Rolling on-disk buffer of short segments, similar to Limelight Rewind
  - Segments from ~5 s before enable to ~5 s after disable are kept as a recording, based on `FMSControlData` (works with a Driver Station alone)
  - `saveRecording` keeps the last N seconds
  - Named by event + match when FMS is attached, otherwise by time
  - Oldest recordings deleted above a disk usage threshold
- Log time is NT server time, the same time base as WPILOG
  - Wall clock only used for filenames and metadata

## Tooling

- `vscode-camera-preview` rewritten from scratch, reads the TOML config
