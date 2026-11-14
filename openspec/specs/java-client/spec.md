# java-client Specification

## Purpose

The `com.team581:spot` Java vendordep that robot code uses to publish Spot's inputs and receive its outputs.

## Requirements

### Requirement: Vendordep distribution

The client SHALL be published to Maven Central as `com.team581:spot`, and installable with the vendordep at `https://spot.frc581.com/vendordep.json`.

#### Scenario: Installing

- **WHEN** a team adds the vendordep URL in WPILib
- **THEN** the `com.team581.spot` classes are available to robot code

### Requirement: Publishes inputs

The client SHALL publish the config string and field layout to Spot's input topics.

#### Scenario: Constructing the client

- **WHEN** robot code constructs `Spot` with `spot.toml` contents and a field layout
- **THEN** both are published to `/Spot/inputs/config` and `/Spot/inputs/fieldLayout`

### Requirement: Per-camera estimate callbacks

The client SHALL deliver each camera's estimates to a callback with the capture time in FPGA seconds and the tag IDs as an ascending `int[]`.

#### Scenario: Estimate arrives

- **WHEN** Spot publishes an estimate for camera `front`
- **THEN** callbacks registered with `camera("front").onEstimate` receive it with its FPGA timestamp

### Requirement: Forward-compatible states

Status enums SHALL map states the client doesn't know to `UNKNOWN` instead of failing.

#### Scenario: Newer Spot

- **WHEN** Spot reports a state added after the client was built
- **THEN** the client reports `UNKNOWN`

### Requirement: No trust policy

The client MUST NOT filter or weight estimates; that SHALL stay in robot code.

#### Scenario: Ambiguous estimate

- **WHEN** Spot publishes an estimate with an alternate pose
- **THEN** the client delivers it unchanged
