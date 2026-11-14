# networktables-protocol Specification

## Purpose

The NT4 contract between Spot and robot code: the topics, structs, timestamps, and states that robot code depends on.

## Requirements

### Requirement: One-way, NT-native protocol

Spot SHALL connect as NT4 client `spot` and SHALL know nothing about the robot beyond its inputs: it MUST NOT read robot state, accept commands, or negotiate tag selection. Outputs SHALL be WPILib structs with published schemas.

#### Scenario: Robot code wants different tags

- **WHEN** robot code wants Spot to ignore a tag
- **THEN** it lists the tag in `ignored_tags` in `spot.toml`, since Spot has no command topic

### Requirement: Input topics

Spot SHALL read its TOML config from `/Spot/inputs/config` and a WPILib `AprilTagFieldLayout` JSON string from `/Spot/inputs/fieldLayout`. It SHALL also read `/FMSInfo` to trigger and name recordings.

#### Scenario: New field layout

- **WHEN** robot code publishes a new field layout
- **THEN** Spot uses it for subsequent estimates

### Requirement: Output topics

Spot SHALL publish `struct:SpotStatus` to `/Spot/outputs/status`, a string to `/Spot/outputs/error`, and for each camera `struct:SpotEstimate` to `/Spot/outputs/cameras/<name>/estimate` and `struct:SpotCameraStatus` to `/Spot/outputs/cameras/<name>/status`.

#### Scenario: Frame without usable tags

- **WHEN** a camera's frame has no usable tags
- **THEN** nothing is published to that camera's `estimate` topic

### Requirement: Capture-time timestamps

Each estimate's NT timestamp SHALL be its frame's capture time in NT server time, with no separate latency field. Spot SHALL publish nothing until NT time sync is acquired.

#### Scenario: Before time sync

- **WHEN** Spot has connected but not yet synced its clock
- **THEN** it publishes no outputs and its state is `waiting_for_time_sync`

### Requirement: Estimate struct

`SpotEstimate` SHALL contain the primary `Pose3d` and its RMS reprojection error, an optional alternate `Pose3d` and its error, a bitmask (`int64`) of tag IDs 0 to 63 used, the average camera-to-tag distance, and the tags' fraction of the image area.

#### Scenario: Single-tag estimate

- **WHEN** an estimate uses only tag 7
- **THEN** `tag_ids` has only bit 7 set

### Requirement: Most fundamental state

`SpotStatus` SHALL contain the version, a state, and `overrides_active`. Its state SHALL be the first problem that applies, in order: `waiting_for_time_sync`, `waiting_for_config`, `invalid_config`, `missing_camera`, `uncalibrated_camera`; otherwise `ready`. Details SHALL be in `/Spot/outputs/error`, which is empty when `ready`. Only cameras marked `required` SHALL affect it.

#### Scenario: Optional camera unplugged

- **WHEN** a camera without `required = true` is disconnected
- **THEN** Spot's state is unaffected

#### Scenario: Required camera uncalibrated

- **WHEN** everything else is fine but a `required` camera has no calibration for its resolution
- **THEN** Spot's state is `uncalibrated_camera`

### Requirement: Camera status

`SpotCameraStatus` SHALL contain a state (`streaming`, `disconnected`, `duplicate_serial`, `uncalibrated`, `falling_behind`), frames processed per second, and dropped frames.

#### Scenario: Camera falling behind

- **WHEN** detection can't keep up with capture
- **THEN** the camera's state is `falling_behind` and `dropped_frames` grows
