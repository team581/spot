---
title: Robot configuration
description: Start robot code's spot-config.json and keep it in sync with Spot.
---

Robot code owns Spot's camera configuration in `src/main/deploy/spot-config.json`.
The robot forwards the file to Spot over NetworkTables, and Spot validates and applies
it. Edits made on the dashboard take priority until robot code matches them.

## Get started

1. Download the [starter configuration](../starter/spot-config.json) to
   `src/main/deploy/spot-config.json` in the robot project.
2. Give each camera a `name` and set `robot_to_camera` if the mount is already
   measured: metres from the robot origin (WPILib NWU: +X forward, +Y left, +Z up)
   and `roll_deg`, `pitch_deg`, `yaw_deg` as in WPILib's `Rotation3d`. Positive
   pitch points the lens down. Otherwise measure it on the dashboard's **Mount** tab.
   Give each camera the capture mode you expect from its datasheet; if the camera
   does not support it, choose a supported mode on its **Tuning** tab.
   Omitted settings use their defaults, and the dashboard fills in `binding_id` and
   `calibration`. The top-level `latency_ms` (default 5) is a fixed allowance for the
   delay between exposure and Spot reading a frame; Spot shifts every capture
   timestamp earlier by it.
3. Publish the file's contents as a string; robot code never parses it. The offseason robot's
   [`VisionConfig.java`](https://github.com/team581/offseason-2026/blob/main/offseason-bot/src/main/java/frc/robot/vision/VisionConfig.java)
   reads it and the shared
   [`com.team581.vision.spot`](https://github.com/team581/offseason-2026/tree/main/shared/src/main/java/com/team581/vision/spot)
   library sends it to Spot.
4. Deploy robot code. Spot's **Changes** page shows **In sync** once it has the file.
5. On the dashboard, [assign each feed](../operator/cameras/#assign-cameras) to a
   camera name, then tune, measure mounts, and calibrate.
6. Use **Changes → Copy spot-config.json**, replace the file in the robot project,
   and deploy. Spot's changes clear once robot code matches them.

## Where settings belong

A setting lives with whoever reads it:

- **Only Spot reads it:** `spot-config.json`. Cameras, capture modes, controls,
  mounts, and processing. The dashboard can edit these, and robot code forwards the
  file without parsing it.
- **Robot code and Spot both read it:** a typed value in robot code, published under
  `/Spot/Config/` in NetworkTables, so the roboRIO never parses JSON. The field
  layout and tag sizes, `maxAgeS`, and `futureToleranceS`.
- **Only robot code reads it:** robot code, never sent to Spot. Fusion, heading use,
  measurement ordering, and the timing uncertainty used to weight vision
  measurements, for example.

## Schema

The starter names the published schema so editors such as VS Code autocomplete
and check the file:

```json
{ "$schema": "https://spot.frc581.com/spot-config.schema.json" }
```

Spot also checks rules the schema cannot express, such as unique camera names and
calibrations that match their camera. Spot reports these errors on the `/Spot/error`
NetworkTables topic.
