---
title: Camera setup
---

## Connect

Open <http://spot.local:5800> or the default maintenance address
<http://192.168.69.170:5800>. For direct Ethernet, give the laptop
`192.168.69.171/24`. The Network page shows current addresses and the robot link.

Use **Network → Jetson address** to change Ethernet settings. Check the new
connection and click **Keep settings** before the trial expires; an unconfirmed
trial rolls back. Both Ethernet ports share one network.

Keep the robot disabled during setup. For bench work without a robot connection,
use **Begin standalone setup** on Network or **Open standalone camera setup** on
the camera page. Follow the displayed lock reason if editing is unavailable.

## Assign cameras

Production camera names come from the robot profile. Select a physical feed,
confirm it matches the camera, then assign an available code-defined name.
For tuning and calibration without a profile, use standalone camera setup.

## Geometry

Measure mounts from the robot origin to the camera optical origin in metres,
using WPILib axes: X forward, Y left, Z up. Positive pitch points the lens down.
Production mounts come from robot code; dashboard **Inspection preview** controls
only change the preview. The [VS Code extension](../vscode-camera-preview/)
can preview mounts beside the Java configuration.

## Tune

Use the camera page's live preview and detection outlines while adjusting exposure
and gain. Undo, redo, and reset controls let you compare settings.

## Calibrate

1. In **Calibration → Board**, enter the measured dimensions and dictionary of
   the actual ChArUco print. Click **Update board**.
2. Add cameras and collect **Fitting captures** with varied board positions,
   distances, and tilts. Keep the board sharp and cover the image edges.
3. Click **Calibrate**, then collect separate **Validation captures** and click
   **Validate**. Follow the reported retry reasons.
4. Review **Results / history**, select passing cameras, and click **Apply selected**.
   Wait for **Applied** before using the result.

Intrinsic calibration does not measure the mount. Recalibrate after replacement,
focus changes, or incompatible optical modes. Use history to restore compatible
calibration records.

## Check on hardware

Before enabling robot fusion, verify measured mounts, calibration, capture
timestamps, field accuracy, multi-camera load, and disconnect/restart recovery.
A passing software test or health check does not establish physical accuracy.
