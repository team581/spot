# jetson-network-settings Specification

## Purpose

The settings that live only on the Jetson (team number, Ethernet addressing, and NetworkTables server) and how they're changed safely.

## Requirements

### Requirement: Jetson-local network settings

Spot SHALL store team number (default 581), Ethernet addressing (DHCP by default, or static), and an optional NetworkTables server override on the Jetson. Without an override, Spot SHALL connect to `10.TE.AM.2` derived from the team number.

#### Scenario: Simulator

- **WHEN** a user sets the NetworkTables server to a laptop's address
- **THEN** Spot connects to the laptop instead of the roboRIO

### Requirement: Trial, confirm, rollback

Addressing changes SHALL be applied as a trial that the user must confirm before a countdown ends; an unconfirmed change SHALL roll back automatically. The maintenance address SHALL stay reachable throughout.

#### Scenario: Unreachable static address

- **WHEN** a user tries a static address and can't reconnect to confirm it
- **THEN** Spot reverts to the previous addressing when the countdown ends

#### Scenario: Confirmed change

- **WHEN** a user reconnects at the new address and confirms before the countdown ends
- **THEN** the new addressing is kept
