# vscode-camera-preview Specification

## Purpose

A VS Code extension that previews the camera mounts in a robot project's `spot.toml` in 3D, without a robot or Jetson.

## Requirements

### Requirement: Preview from spot.toml

The extension SHALL read `src/main/deploy/spot.toml` and show each camera's mount in a 3D preview, opening beside the file automatically unless `spot.cameraPreview.autoOpen` is off.

#### Scenario: Opening the config

- **WHEN** a user opens `spot.toml` in a trusted workspace
- **THEN** the preview opens beside it

### Requirement: Tolerates invalid files

While the file has errors, the preview SHALL keep showing the last valid version.

#### Scenario: Half-typed edit

- **WHEN** the user saves `spot.toml` with a syntax error
- **THEN** the preview keeps the last valid cameras

### Requirement: Missing calibration warning

The preview SHALL warn when a camera's mode has no calibration.

#### Scenario: New mode

- **WHEN** a camera's `mode` resolution has no entry in `calibrations`
- **THEN** the preview shows a warning for that camera
