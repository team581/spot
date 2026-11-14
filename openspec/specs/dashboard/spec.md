# dashboard Specification

## Purpose

The web dashboard served by Spot, which covers everything needed to bring up, tune, and review Spot without other tools.

## Requirements

### Requirement: Complete bring-up

The dashboard SHALL cover camera assignment, tuning, calibration, mount checks, config, network settings, system health, recording review, and docs, so bring-up needs no other tools.

#### Scenario: New robot

- **WHEN** a team sets up Spot on a new robot
- **THEN** every step from assigning cameras to checking mounts is done on the dashboard

### Requirement: Camera views

The dashboard SHALL show a camera grid with tag overlays, and a 3D field view showing field tags, each camera's robot estimate, the camera on that robot, and lines to its tags.

#### Scenario: Checking a mount

- **WHEN** several cameras see tags
- **THEN** the field view draws each camera's robot estimate so mismatched mounts stand out

### Requirement: Camera tuning

The dashboard SHALL let users assign connected devices to camera names, and set each camera's mode, exposure, and gain while watching its live view and detections table.

#### Scenario: Adding a camera

- **WHEN** a user assigns a newly plugged-in device to a name and adjusts its exposure
- **THEN** both changes are saved as overrides

### Requirement: Config page

The Config page SHALL list overrides next to robot code's values, offer the merged config as copyable TOML, and accept pasted TOML to replace the config as overrides.

#### Scenario: Saving changes to robot code

- **WHEN** a user copies the merged config into `spot.toml` and deploys robot code
- **THEN** Spot deletes the overrides that robot code's config now matches

### Requirement: Network and system pages

The dashboard SHALL let users change team number, DHCP or static addressing, and the NT server override, and SHALL show CPU, GPU, temperature, and per-camera FPS.
Every page SHALL show the Git commit Spot was built from and that commit's date, and SHALL mark builds with uncommitted changes.

#### Scenario: Checking what's deployed

- **WHEN** a user wants to know which build a Jetson is running
- **THEN** the dashboard shows its commit, linked to GitHub, and the commit's date

#### Scenario: Overheating

- **WHEN** the Jetson is running hot
- **THEN** the System page shows its temperature

### Requirement: Recordings page

The dashboard SHALL list recordings for MCAP download and replay them in the browser with the 3D field view and camera images with tag overlays.

#### Scenario: Reviewing a match

- **WHEN** a user replays a match recording
- **THEN** the field view shows each camera's estimates next to its images

### Requirement: Embedded docs

The dashboard SHALL embed the Astro docs site.

#### Scenario: No internet at an event

- **WHEN** a user opens the docs from the dashboard without internet access
- **THEN** the docs load from the Jetson

### Requirement: Overrides warning

The dashboard SHALL warn while any overrides are active.

#### Scenario: Unsaved tuning

- **WHEN** a user changed exposure on the dashboard and hasn't copied it into robot code
- **THEN** the dashboard shows an overrides warning
