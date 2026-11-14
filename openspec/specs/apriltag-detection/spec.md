# apriltag-detection Specification

## Purpose

Finding AprilTags in camera frames, and how quickly Spot turns frames into pose estimates on the Jetson Orin.

## Requirements

### Requirement: tag36h11 only

Spot SHALL detect tag36h11 tags only.

#### Scenario: Other tag family

- **WHEN** a frame contains a tag from another family
- **THEN** no detection is reported for it

### Requirement: Jetson hardware acceleration

Spot SHALL use the Jetson Orin's hardware acceleration for image decoding and tag detection, instead of doing that work on the CPU alone.

#### Scenario: Running on the Jetson

- **WHEN** Spot processes camera frames on a Jetson Orin
- **THEN** decoding and detection use the Jetson's hardware accelerators

### Requirement: Estimate latency

With four cameras streaming at the same time, Spot SHALL publish each frame's pose estimate no more than 20 ms after receiving the frame, and SHOULD do so in under 5 ms.

#### Scenario: Four cameras at full rate

- **WHEN** four cameras stream at `1280x800@120` and all see tags
- **THEN** each estimate is published within 20 ms of its frame being received, and typically within 5 ms

### Requirement: Distortion-aware detection

When a camera has a calibration for its resolution, detection SHALL account for its lens distortion.

#### Scenario: Tag near the image edge

- **WHEN** a calibrated camera sees a tag near the edge of the image
- **THEN** the tag's corners are located with the lens distortion taken into account

### Requirement: Measurable detector changes

`spot-vision corpus` SHALL score detection accuracy and speed on labelled frames.

#### Scenario: Evaluating a detector change

- **WHEN** a developer runs `spot-vision corpus`
- **THEN** it reports accuracy and timing against the labelled frames
