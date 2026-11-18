---
title: Jetson
description: Spot's hardware, firmware, addresses, ports, files, and recordings.
---

## Hardware

| Part     | Model                                                                                                                              |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Computer | Jetson Orin Nano 8GB on a Seeed reComputer Robotics J401 carrier                                                                   |
| Cameras  | [Swyft USB camera](https://swyftrobotics.com/electrical/swyft-usb-camera): OV9281 global shutter, mono, MJPEG, 1280×800 at 120 FPS |

Spot uses UVC cameras over V4L2, MJPEG only.

## Firmware

| Item    | Value                                                                       |
| ------- | --------------------------------------------------------------------------- |
| Release | Seeed JetPack 7.2 for the J401 with an Orin Nano 8GB                        |
| Version | `39.2.0-gcid-45755727`, in `/sys/class/dmi/id/bios_version`                 |
| Image   | `mfi_recomputer-robo-orin-nano-8g-j401-gmsl-7.2.0-39.2.0-2026-06-22.tar.gz` |
| SHA-256 | `23b68b43e630d166e5079f72509c71ea0e13f76e372ddd06fe22df5494ad3f41`          |

## Debug port

The USB 2.0 Type-C port, labeled Device Mode/Debug, is the only port that can flash the J401.
The DIP switch next to it sets what the port connects to:

| Position     | Port connects to                                  | On power-up          |
| ------------ | ------------------------------------------------- | -------------------- |
| Debug        | Serial console (Silicon Labs CP210x), 115200 baud | Boots normally       |
| RESET or REC | The Jetson's USB, as `0955:7523 NVIDIA Corp. APX` | Enters recovery mode |

## Network

| Name                 | Value                                                                             |
| -------------------- | --------------------------------------------------------------------------------- |
| Hostname             | `spot.local` (mDNS)                                                               |
| Maintenance address  | `10.5.81.11/24`, always present                                                   |
| Other addresses      | DHCP by default; set on the **Network** page                                      |
| NetworkTables server | `10.TE.AM.2` from the team number (default 581), unless overridden on **Network** |

Both Ethernet ports are bridged onto one network.

## Ports

| Port | Service                                          |
| ---- | ------------------------------------------------ |
| 22   | SSH                                              |
| 80   | Dashboard, HTTP API at `/api/`, docs at `/docs/` |
| 5800 | Same as 80                                       |
| 5801 | Foxglove WebSocket (live dashboard views)        |

## Access

| Item       | Value                                                                   |
| ---------- | ----------------------------------------------------------------------- |
| SSH user   | `team581`, passwordless `sudo`                                          |
| SSH key    | `nix/maintenance_ed25519`; `mise run jetson:ssh` uses it                |
| Service    | `spot-vision` (systemd)                                                 |
| State      | `/var/lib/spot-vision`: cached robot inputs, overrides, Jetson settings |
| Partitions | `SPOT_EFI` (FAT32, `/boot`), `SPOT_ROOT` (ext4, `/`)                    |

## Recordings

Spot keeps a rolling buffer and saves MCAP files from about 5 s before each enable to 5 s after it disables.
Enables come from `/FMSInfo/FMSControlData`, so a Driver Station alone is enough.
Files are named by event and match when an FMS is attached, otherwise by time.
Log times are NT server time.

Each recording holds:

- Camera images, at most 30 per second per camera
- Tag detections and estimates, at full rate
- Camera status
- The effective config and field layout, at start and on each change
- Service logs

The oldest recordings are deleted once disk usage passes 80%.
