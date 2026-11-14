# recording Specification

## Purpose

Automatic MCAP recording of what Spot saw around each robot enable, for review on the dashboard or in Foxglove.

## Requirements

### Requirement: MCAP recordings matching live views

Recordings SHALL be MCAP files that open in Foxglove, and the dashboard's live views SHALL show the same data that recordings store.

#### Scenario: Opening in Foxglove

- **WHEN** a user downloads a recording and opens it in Foxglove
- **THEN** it shows the same images, detections, and estimates the dashboard showed live

### Requirement: Recording contents

A recording SHALL contain each camera's images at up to 30 FPS, tag detections (corners and IDs) and estimates at full rate, camera status, the effective config and field layout at start and on every change, and service logs.

#### Scenario: Config changes mid-match

- **WHEN** the effective config changes during a recording
- **THEN** the new config is logged at that point

### Requirement: Recordings around enables

While Spot is synced with NT server time, it SHALL save a recording from about 5 s before each enable to about 5 s after it disables, based on `/FMSInfo/FMSControlData`. Enables while unsynced SHALL NOT be recorded. Recordings SHALL be named by event and match when an FMS is attached, otherwise by time.

#### Scenario: Practice with a Driver Station

- **WHEN** the robot is enabled from a Driver Station with no FMS
- **THEN** a recording named by time is saved

#### Scenario: Qualification match

- **WHEN** the robot is enabled by an FMS
- **THEN** the recording is named by event and match

### Requirement: Fast replay

Replaying a recording SHALL show detections and estimates without first downloading its images.

#### Scenario: Opening a replay

- **WHEN** the dashboard opens a recording
- **THEN** estimates and detections load before the images do

### Requirement: NT server time base

Log times SHALL be NT server time, the same time base as WPILOG. Wall-clock time SHALL only be used for filenames and metadata.

#### Scenario: Comparing with robot logs

- **WHEN** a recording and the robot's WPILOG are opened together
- **THEN** their timestamps line up without conversion

### Requirement: Bounded disk use

Spot SHALL delete the oldest recordings once disk usage passes 80%.

#### Scenario: Disk filling up

- **WHEN** disk usage exceeds 80%
- **THEN** the oldest recordings are deleted until it's below
