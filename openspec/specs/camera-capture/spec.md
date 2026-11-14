# camera-capture Specification

## Purpose

How Spot finds configured USB cameras, applies their settings, and gets timestamped frames to detection with the lowest latency.

## Requirements

### Requirement: USB UVC cameras, MJPEG only

Spot SHALL support USB UVC cameras streaming MJPEG, and no other camera interfaces or image formats.

#### Scenario: Camera mode

- **WHEN** a camera is configured with a `mode` of `WIDTHxHEIGHT@FPS`
- **THEN** Spot captures MJPEG at that resolution and frame rate

### Requirement: Matching devices to cameras

Each configured camera SHALL be matched by its required `serial`, and by its optional USB `port` path when several cameras share a serial. Spot MUST NOT guess when the match is ambiguous.

#### Scenario: Unique serial

- **WHEN** exactly one connected device has the camera's `serial`
- **THEN** Spot captures from that device

#### Scenario: Shared serial without a port

- **WHEN** several connected devices match the camera's `serial` and no `port` tells them apart
- **THEN** the camera's state is `duplicate_serial` and Spot captures from none of them

#### Scenario: No match

- **WHEN** no connected device matches the camera's `serial` and `port`
- **THEN** the camera's state is `disconnected`

### Requirement: Limited camera controls

Spot SHALL expose only mode, `auto_exposure` (`manual` or `aperture_priority`), `exposure_time_absolute`, and `gain`. Every other control, and any of these left unset, SHALL be reset to the camera's default.

#### Scenario: Unset control

- **WHEN** a camera's config doesn't set `gain`
- **THEN** Spot resets the camera's gain to its default

### Requirement: Reconnecting cameras

A camera that disconnects or fails to open SHALL be reconnected automatically, without affecting other cameras or the service.

#### Scenario: Unplugged and replugged

- **WHEN** a streaming camera is unplugged and later plugged back in
- **THEN** it reports `disconnected` while unplugged and returns to `streaming` on its own

### Requirement: Capture-time timestamps

Each frame SHALL be timestamped with its capture time in NT server time. There SHALL be no per-camera latency setting.

#### Scenario: Frame time

- **WHEN** a frame is captured
- **THEN** its timestamp is when the camera captured it, in NT server time

### Requirement: Latest frame wins

Spot SHALL always process each camera's newest frame, and SHALL drop and count frames it can't keep up with instead of queueing them. A slow camera SHALL NOT delay the others.

#### Scenario: Processing slower than capture

- **WHEN** a camera delivers a new frame before Spot started processing the previous one
- **THEN** the previous frame is dropped, the camera's `dropped_frames` count increases, and a camera that keeps dropping reports `falling_behind`
