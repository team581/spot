---
title: NetworkTables
description: Spot's NetworkTables topics, structs, and states.
---

Spot is NT4 client `spot`.
It publishes nothing until its clock is synced with the NT server.

## Topics

| Topic                                   | Direction    | Type                      | Contents                                            |
| --------------------------------------- | ------------ | ------------------------- | --------------------------------------------------- |
| `/Spot/inputs/config`                   | robot → Spot | `string`                  | [`spot.toml`](../config/) contents                  |
| `/Spot/inputs/fieldLayout`              | robot → Spot | `string`                  | WPILib `AprilTagFieldLayout` JSON                   |
| `/Spot/outputs/status`                  | Spot → robot | `struct:SpotStatus`       | Overall status                                      |
| `/Spot/outputs/error`                   | Spot → robot | `string`                  | Details for a non-`ready` state; empty when `ready` |
| `/Spot/outputs/cameras/<name>/estimate` | Spot → robot | `struct:SpotEstimate`     | One per frame with usable tags                      |
| `/Spot/outputs/cameras/<name>/status`   | Spot → robot | `struct:SpotCameraStatus` | Camera status                                       |
| `/FMSInfo/*`                            | read by Spot |                           | Starts and names recordings                         |

Each estimate's NT timestamp is its frame's capture time, in NT server time.

## `SpotEstimate`

| Field                  | Type     | Description                                                       |
| ---------------------- | -------- | ----------------------------------------------------------------- |
| `primary`              | `Pose3d` | Best-fitting field-relative robot pose.                           |
| `primary_error`        | `double` | RMS reprojection error of `primary`, in pixels.                   |
| `has_alternate`        | `bool`   | Whether `alternate` is set.                                       |
| `alternate`            | `Pose3d` | Second plausible robot pose.                                      |
| `alternate_error`      | `double` | RMS reprojection error of `alternate`, in pixels.                 |
| `tag_ids`              | `int64`  | Bitmask of the tag IDs used; bit _n_ is tag _n_, for IDs 0 to 63. |
| `average_tag_distance` | `double` | Average camera-to-tag distance, in meters.                        |
| `tag_area`             | `double` | The tags' share of the image area, 0 to 1.                        |

## `SpotStatus`

| Field              | Type       | Description                                     |
| ------------------ | ---------- | ----------------------------------------------- |
| `version`          | `char[16]` | Spot's version.                                 |
| `state`            | `uint8`    | See below.                                      |
| `overrides_active` | `bool`     | Dashboard overrides change robot code's config. |

`state` is the first problem in this list that applies:

| Value | Name                    | Meaning                                                      |
| ----- | ----------------------- | ------------------------------------------------------------ |
| 0     | `ready`                 | No problems.                                                 |
| 1     | `waiting_for_time_sync` | Not yet synced with the NT server.                           |
| 2     | `waiting_for_config`    | No config or field layout received, and none cached.         |
| 3     | `invalid_config`        | The config was rejected.                                     |
| 4     | `missing_camera`        | A `required` camera is `disconnected` or `duplicate_serial`. |
| 5     | `uncalibrated_camera`   | A `required` camera has no calibration for its resolution.   |

Cameras that aren't `required` don't affect `state`.

## `SpotCameraStatus`

| Field            | Type     | Description                                           |
| ---------------- | -------- | ----------------------------------------------------- |
| `state`          | `uint8`  | See below.                                            |
| `fps`            | `double` | Frames processed per second.                          |
| `dropped_frames` | `uint32` | Frames dropped because detection fell behind capture. |

| Value | Name               | Meaning                                                            |
| ----- | ------------------ | ------------------------------------------------------------------ |
| 0     | `streaming`        | Running normally.                                                  |
| 1     | `disconnected`     | No device matches the camera's `serial` and `port`.                |
| 2     | `duplicate_serial` | Several devices match its `serial` and no `port` tells them apart. |
| 3     | `uncalibrated`     | No calibration for its mode's resolution.                          |
| 4     | `falling_behind`   | Detection can't keep up with capture, so frames are dropped.       |
