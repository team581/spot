---
title: spot.toml
description: Every key in Spot's robot config.
---

Robot code publishes `src/main/deploy/spot.toml` to `/Spot/inputs/config`.
The [JSON Schema](../../spot-config.schema.json) describes the same keys; add `#:schema https://spot.frc581.com/spot-config.schema.json` as the first line for editor checks.
A [starter file](../../starter/spot.toml) has one camera.

Unknown keys are errors.
An invalid config is rejected, the last valid one keeps running, and the reason is published to `/Spot/outputs/error`.

## Top level

| Key            | Type         | Default | Description                                                    |
| -------------- | ------------ | ------- | -------------------------------------------------------------- |
| `ignored_tags` | array of int | `[]`    | Tag IDs never used for pose estimation.                        |
| `recording`    | table        |         | See [`[recording]`](#recording).                               |
| `cameras`      | table        | `{}`    | Cameras keyed by name. See [`[cameras.<name>]`](#camerasname). |

## `[recording]`

| Key                      | Type  | Default | Description                                                  |
| ------------------------ | ----- | ------- | ------------------------------------------------------------ |
| `enabled`                | bool  | `true`  | Record matches and robot enables.                            |
| `image_fps`              | float | `30`    | Most camera images stored per camera per second. At least 0. |
| `max_disk_usage_percent` | float | `80`    | Delete the oldest recordings above this disk usage. 1 to 99. |

## `[cameras.<name>]`

Names may use letters, digits, `-`, and `_`.

| Key            | Type   | Default        | Description                                                                            |
| -------------- | ------ | -------------- | -------------------------------------------------------------------------------------- |
| `serial`       | string | required       | USB serial number.                                                                     |
| `port`         | string |                | USB port path, such as `1-2.2`. Required when several cameras share a `serial`.        |
| `required`     | bool   | `false`        | Spot isn't `ready` unless this camera is streaming and calibrated.                     |
| `mode`         | string | `1280x800@120` | Capture mode, `WIDTHxHEIGHT@FPS`.                                                      |
| `controls`     | table  |                | See [`controls`](#controls).                                                           |
| `mount`        | table  | all `0`        | See [`mount`](#mount).                                                                 |
| `calibrations` | table  | `{}`           | Calibrations keyed by resolution, `WIDTHxHEIGHT`. See [`calibrations`](#calibrations). |

No two cameras may have the same `serial` and `port`.

### `controls`

Unset controls reset to the camera's default.

| Key                      | Type   | Description                                                                 |
| ------------------------ | ------ | --------------------------------------------------------------------------- |
| `auto_exposure`          | string | `manual` or `aperture_priority`.                                            |
| `exposure_time_absolute` | int    | Exposure time in units of 100 µs. Applies when `auto_exposure` is `manual`. |
| `gain`                   | int    | Sensor gain, in the camera's units.                                         |

### `mount`

The robot-to-camera transform, as WPILib's `Transform3d`.
The robot origin is its center at floor level.

| Key     | Unit    | Direction                                         |
| ------- | ------- | ------------------------------------------------- |
| `x`     | meters  | +X forward                                        |
| `y`     | meters  | +Y left                                           |
| `z`     | meters  | +Z up                                             |
| `roll`  | degrees | `Rotation3d` roll                                 |
| `pitch` | degrees | `Rotation3d` pitch; positive points the lens down |
| `yaw`   | degrees | `Rotation3d` yaw; positive turns left             |

```toml
mount = { x = 0.3, y = -0.25, z = 0.2, roll = 0.0, pitch = 15.0, yaw = -30.0 }
```

### `calibrations`

Pinhole intrinsics with OpenCV's five-coefficient distortion model, as produced by the dashboard.
A camera uses the calibration matching its `mode`'s resolution; without one it is `uncalibrated` and its estimates aren't published.

| Key          | Type             | Description                                                    |
| ------------ | ---------------- | -------------------------------------------------------------- |
| `fx`, `fy`   | float            | Focal lengths in pixels. Positive.                             |
| `cx`, `cy`   | float            | Principal point in pixels. Inside the image.                   |
| `distortion` | array of 5 float | `[k1, k2, p1, p2, k3]`.                                        |
| `rms`        | float            | RMS reprojection error of the calibration in pixels. Optional. |

## Not in `spot.toml`

Team number, Ethernet addressing, and the NetworkTables server are Jetson settings, set on the dashboard's **Network** page.
The field layout comes from `/Spot/inputs/fieldLayout`.
