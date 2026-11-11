---
title: Robot configuration
description: Keep Spot's TOML configuration in robot code and read its estimates.
---

Robot code owns Spot's configuration in `src/main/deploy/spot.toml`. Robot code
publishes the file's contents as a string; Spot validates and applies it. Spot keeps
the last configuration it received, so bench work only needs the robot to have
connected once.

## Get started

1. Download the [starter configuration](../starter/spot.toml) to
   `src/main/deploy/spot.toml`.
2. Add a `[cameras.<name>]` table per camera. Names appear in NetworkTables topics.
   Select each camera by `serial` (preferred) or physical `port`, not both. The
   dashboard can fill these in: see [assign cameras](../operator/cameras/#assign-cameras).
3. Publish the file to `/Spot/inputs/config` and the field layout
   (WPILib `AprilTagFieldLayout` JSON) to `/Spot/inputs/fieldLayout`.
4. Deploy robot code, then tune and calibrate on the dashboard.
5. Copy the merged TOML from the dashboard's **Config** page into
   `spot.toml` and deploy. Dashboard overrides clear once robot code matches them.

The `#:schema` line lets editors with TOML schema support (for example
[Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml))
autocomplete and check the file against the
[published schema](../spot-config.schema.json). Spot also checks rules the schema
cannot express and reports them on `/Spot/outputs/error`. An invalid configuration
is rejected and the last valid one keeps running.

Team number, IP address, and the NetworkTables server are set on the Jetson, not here.

## Mounts and pose estimates

`mount` is the robot-to-camera transform: meters on WPILib axes (+X forward, +Y left,
+Z up) and degrees as `Rotation3d(roll, pitch, yaw)`. Positive pitch points the lens
down. Unset values are 0.

Spot assumes the robot is flat on the floor (zero height, roll, and pitch) and fits
every visible tag at once, per camera and frame. It only ignores tags that are not in
the field layout, are listed in `ignored_tags`, or are seen by an uncalibrated
camera. All trust decisions belong to robot code.

## NetworkTables

Spot connects as NT4 client `spot` and publishes nothing until time sync is
acquired. Values are WPILib structs with published schemas.

| Topic                                   | Type                      | Contents                                    |
| --------------------------------------- | ------------------------- | ------------------------------------------- |
| `/Spot/inputs/config`                   | string                    | `spot.toml` contents, from robot code       |
| `/Spot/inputs/fieldLayout`              | string                    | `AprilTagFieldLayout` JSON, from robot code |
| `/Spot/inputs/saveRecording`            | double                    | Optional: keep the last N seconds           |
| `/Spot/outputs/status`                  | `struct:SpotStatus`       | Version, state, overrides active            |
| `/Spot/outputs/error`                   | string                    | Details for a non-ready state               |
| `/Spot/outputs/cameras/<name>/estimate` | `struct:SpotEstimate`     | Pose estimate, only for frames with tags    |
| `/Spot/outputs/cameras/<name>/status`   | `struct:SpotCameraStatus` | State, FPS, dropped frames                  |

Each estimate's NT timestamp is the frame's capture time in NT server time; pass it
straight to `addVisionMeasurement`. An estimate holds a primary `Pose3d` and its RMS
reprojection error in pixels, an optional alternate candidate (disambiguate it, for
example, by heading), a bitmask of the tag IDs (0–63) used, the average
camera-to-tag distance in meters, and the tags' share of the image area.

`SpotStatus.state` reports the most fundamental problem: `ready`,
`waiting_for_time_sync`, `waiting_for_config`, `invalid_config`, `missing_camera`, or
`uncalibrated_camera`. Only cameras marked `required` affect it. Each camera's state
is `streaming`, `disconnected`, `duplicate_serial`, `uncalibrated`, or
`falling_behind`.

## Recordings

Spot records MCAP files around every enable (from about 5 s before to 5 s after),
using `/FMSInfo` from the Driver Station, and names them by event and match when an
FMS is attached. Setting `/Spot/inputs/saveRecording` to N keeps the last N seconds
(up to 60). Recording log times are NT server time, the same time base as WPILOG.
The `[recording]` table sets the image rate and disk limit.
