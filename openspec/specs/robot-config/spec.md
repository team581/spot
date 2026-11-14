# robot-config Specification

## Purpose

How Spot gets its camera and tag configuration from robot code, validates it, caches it, and layers temporary dashboard overrides on top.

## Requirements

### Requirement: Robot code owns the config

Robot code SHALL publish `spot.toml` as a string to `/Spot/inputs/config` and the field layout to `/Spot/inputs/fieldLayout`, and Spot SHALL apply whatever arrives. The config SHALL cover cameras (name, `serial`, `port`, `required`, mode, controls, mount, calibrations) and `ignored_tags`.

#### Scenario: Robot code starts

- **WHEN** robot code publishes a new config
- **THEN** Spot applies it without a restart

### Requirement: Invalid config never stops Spot

Unknown keys and invalid values SHALL make the config invalid. An invalid config SHALL be rejected, the last valid config SHALL keep running, and the reason SHALL be published to `/Spot/outputs/error`.

#### Scenario: Typo in a key

- **WHEN** robot code publishes a config with an unknown key
- **THEN** Spot reports `invalid_config` with the reason and keeps running the last valid config

### Requirement: Published JSON Schema

A JSON Schema for `spot.toml`, matching exactly what Spot accepts, SHALL be published at `https://spot.frc581.com/spot-config.schema.json` for editor validation.

#### Scenario: Editing in VS Code

- **WHEN** `spot.toml` starts with the `#:schema` line
- **THEN** the editor validates and completes keys against the schema

### Requirement: Cached inputs

Spot SHALL cache the last config and field layout it received on the Jetson and use them until robot code publishes new ones.

#### Scenario: Bench use without a robot

- **WHEN** Spot starts with no robot connected
- **THEN** it runs the cameras from the cached config

### Requirement: Jetson-local settings stay out of config

Team number, Ethernet addressing, and the NetworkTables server SHALL NOT be in `spot.toml`, because Spot needs them before it can receive it.

#### Scenario: Swapping a Jetson

- **WHEN** a Jetson is replaced on a robot
- **THEN** the new Jetson gets every camera setting from robot code, and only network settings need setting on it

### Requirement: Dashboard overrides

Changes made on the dashboard SHALL be stored as overrides persisted on the Jetson, merged over robot code's config, and winning wherever they differ. Spot SHALL delete an override once robot code's config matches it, and SHALL report `overrides_active` in its status while any remain.

#### Scenario: Override copied into robot code

- **WHEN** robot code publishes a config that matches an override
- **THEN** Spot deletes the override, and `overrides_active` turns false once none remain

#### Scenario: Pasting a config

- **WHEN** a user pastes a TOML config on the dashboard
- **THEN** it is stored as overrides, so discarding overrides returns to robot code's config
