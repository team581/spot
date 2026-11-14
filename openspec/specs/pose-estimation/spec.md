# pose-estimation Specification

## Purpose

How Spot turns one camera's tag detections into a field-relative robot pose estimate, leaving every trust decision to robot code.

## Requirements

### Requirement: Stateless estimates

Spot SHALL produce at most one estimate per camera per frame, with no smoothing over time and no fusion across cameras.

#### Scenario: Two cameras see tags

- **WHEN** two cameras each see tags in the same instant
- **THEN** each publishes its own estimate, and neither affects the other

### Requirement: Multi-tag 6-DOF robot pose

Each estimate SHALL be a field-relative 6-DOF robot pose (x, y, z, roll, pitch, yaw), using the camera's mount and all of the frame's usable tags together.

#### Scenario: Several tags in view

- **WHEN** a frame contains several tags in the field layout
- **THEN** one robot pose is estimated from all of them

### Requirement: Physically plausible poses

When the visible tags barely constrain height, roll, and pitch, estimates SHALL stay near a robot flat on the floor. When tags clearly show a tilt, the estimate SHALL report it.

#### Scenario: Single far tag

- **WHEN** only one distant tag is visible
- **THEN** the estimate stays near the floor instead of returning a physically impossible pose

#### Scenario: Robot climbing

- **WHEN** several tags clearly show the robot is tilted
- **THEN** the estimate reports the tilt

### Requirement: Primary and alternate candidates

Each estimate SHALL report the best-fitting pose as `primary` and MAY report a second plausible pose as `alternate`, only when it fits within three times the primary's reprojection error.

#### Scenario: One tag seen head-on

- **WHEN** a single tag is seen nearly head-on
- **THEN** the mirror-image pose is reported as `alternate` when it fits within three times the primary's error, so robot code can choose by heading

### Requirement: No trust policy in Spot

Spot SHALL only drop tags that aren't in the field layout or are listed in `ignored_tags`. It MUST NOT reject estimates for distance, ambiguity, or being off the field; each estimate SHALL instead carry reprojection error, tag IDs, average tag distance, and tag image area.

#### Scenario: Ignored tag

- **WHEN** a frame contains a tag listed in `ignored_tags`
- **THEN** that tag isn't used for the estimate

#### Scenario: Far, ambiguous estimate

- **WHEN** an estimate comes from one distant tag
- **THEN** Spot still publishes it, with the metrics robot code needs to judge it

### Requirement: Uncalibrated cameras still estimate

A camera without a calibration for its resolution SHALL still estimate, assuming the Swyft USB camera's factory calibration scaled to the resolution.

#### Scenario: New camera

- **WHEN** a camera has no calibration for its mode's resolution
- **THEN** it reports `uncalibrated` and still publishes estimates
