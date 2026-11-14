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

### Requirement: Static address entry

A static Ethernet address SHALL be entered as a single IPv4 host address without a prefix, and Spot SHALL apply it on a /24 subnet. Spot SHALL report the configured and pending static address without a prefix.

#### Scenario: Bare address

- **WHEN** a user tries the static address `10.5.81.12`
- **THEN** Spot applies `10.5.81.12` on a /24 subnet and shows the address as `10.5.81.12`

#### Scenario: Address with a prefix

- **WHEN** a user tries the static address `10.5.81.12/24`
- **THEN** Spot rejects the change and keeps the current addressing

#### Scenario: Unusable host address

- **WHEN** a user tries a network, broadcast, loopback, or multicast address, such as `10.5.81.0` or `10.5.81.255`
- **THEN** Spot rejects the change and keeps the current addressing
