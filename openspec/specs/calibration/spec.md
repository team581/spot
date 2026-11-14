# calibration Specification

## Purpose

Camera intrinsic calibration with a ChArUco board, run on the Jetson and guided from the dashboard, producing calibrations that end up in robot config.

## Requirements

### Requirement: On-device ChArUco calibration

Calibration SHALL run on the Jetson from the dashboard, using a ChArUco board, with live board detection and a coverage hint showing which areas of the image still need views.

#### Scenario: Capturing views

- **WHEN** a user captures views during calibration
- **THEN** the dashboard shows the detected board live and shades the image areas not yet covered

### Requirement: Solve quality gates

A solve SHALL require a minimum number of views, SHALL drop outlier views on its own, and SHALL be rejected when its RMS reprojection error exceeds a threshold.

#### Scenario: Too few views

- **WHEN** a user solves with fewer than the minimum number of views
- **THEN** the solve is refused

#### Scenario: High error

- **WHEN** the RMS error after dropping outliers is above the threshold
- **THEN** the calibration is rejected and the user is asked to capture more views

### Requirement: Five-coefficient distortion model

Calibrations SHALL use pinhole intrinsics with OpenCV's five-coefficient distortion model (`k1, k2, p1, p2, k3`).

#### Scenario: Calibration result

- **WHEN** a solve succeeds
- **THEN** it produces `fx`, `fy`, `cx`, `cy`, five distortion coefficients, and the RMS error

### Requirement: Configurable, printable board

The board geometry SHALL be configurable, and the dashboard SHALL generate a printable board matching it.

#### Scenario: Measured square differs

- **WHEN** a user saves a measured square and marker size
- **THEN** detection and the printable board use the new geometry

### Requirement: Results become overrides

An applied calibration SHALL be stored as a dashboard override keyed by camera name and resolution, to be copied into the robot's `spot.toml`.

#### Scenario: Applying a calibration

- **WHEN** a user applies a calibration for a camera at 1280x800
- **THEN** the camera's `calibrations."1280x800"` is overridden and the camera is no longer `uncalibrated` at that resolution
