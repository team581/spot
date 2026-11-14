# jetson-platform Specification

## Purpose

How the Jetson that runs Spot is deployed, reached, and kept running, independent of what the vision service does.

## Requirements

### Requirement: Reproducible deploys with rollback

The Jetson's entire system SHALL be built from this repository. A new build SHALL be deployable as a test that doesn't become the boot default, and a switched build SHALL be possible to roll back.

#### Scenario: Testing a build

- **WHEN** a new build is deployed as a test
- **THEN** it runs immediately, and a reboot returns to the previous build

#### Scenario: Rolling back

- **WHEN** a switched build misbehaves
- **THEN** the previous build can be restored as the boot default

### Requirement: Recovers from hangs

The vision service SHALL be restarted automatically if it crashes or stops responding.

#### Scenario: Service hangs

- **WHEN** the vision service stops responding
- **THEN** it is restarted without anyone intervening

### Requirement: Stable addresses

The Jetson SHALL be reachable as `spot.local` over mDNS and at the fixed maintenance address `10.5.81.11/24`, whatever its other network settings, from either Ethernet port.

#### Scenario: Unknown DHCP address

- **WHEN** a laptop is plugged into either Ethernet port and doesn't know Spot's DHCP address
- **THEN** it can reach Spot at `10.5.81.11`

### Requirement: Service ports

The dashboard SHALL be served on ports 80 and 5800, with the HTTP API at `/api/` and the docs at `/docs/`, and live views SHALL be served over a Foxglove WebSocket on port 5801.

#### Scenario: Opening the dashboard

- **WHEN** a browser opens `http://spot.local/`
- **THEN** the dashboard loads

### Requirement: No access control

Spot SHALL NOT require authentication for the dashboard, API, or WebSocket.

#### Scenario: Any device on the robot network

- **WHEN** any device on the robot network opens the dashboard
- **THEN** it has full access without signing in
