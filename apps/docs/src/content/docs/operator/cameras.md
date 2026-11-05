---
title: Camera setup
---

## Connect

Open <http://spot.local:5800> or the default maintenance address
<http://192.168.69.170:5800>. For direct Ethernet, give the laptop
`192.168.69.171/24`. The Network page shows current addresses and the robot link.

Fresh images request a DHCP address and also keep the maintenance address.
Use **Network → Connection** to set the NetworkTables team number; it reconnects
immediately and saves the selection across reboots.
Changing the team number does not change a static Jetson IP address.

Use **Network → Jetson address** to change Ethernet settings. Check the new
connection and click **Keep settings** before the trial expires; an unconfirmed
trial rolls back. Both Ethernet ports share one network.

Camera settings can be adjusted while the robot is enabled. For bench work without a robot connection,
use **Begin standalone setup** on Network or **Open standalone camera setup** on
the camera page. Follow the displayed lock reason if editing is unavailable.

## Assign cameras

Production camera names come from the robot profile. Select a physical feed,
confirm it matches the camera, then assign an available code-defined name.
For tuning and calibration without a profile, use standalone camera setup.

## Geometry

Measure mounts from the robot origin to the camera optical origin in metres,
using WPILib axes: X forward, Y left, Z up. Positive pitch points the lens down.
Production mounts come from robot code. Use **Inspection preview** to adjust a
mount, then **Save mount override**. The saved mount is used by both Spot and
robot localization until the override is cleared.
The [VS Code extension](../vscode-camera-preview/) previews deployed mounts.

## Tune

Use the camera page's live preview and detection outlines while adjusting exposure
and gain. Undo, redo, and reset controls let you compare settings.

## Saved settings

Robot code supplies defaults in `src/main/deploy/spot-config.json`. Dashboard edits
override them and persist across reconnects, restarts, and deployments.
Use **System → Robot configuration** to clear individual overrides
or all of them. **Read deployed defaults** only loads the editor; it does not clear
overrides.

To adopt tuned settings in robot code, use **Read current configuration → Download
spot-config.json**, replace the file in the robot project, and deploy. Clear the
corresponding overrides when ready to use the deployed values again.

## Calibrate

1. In **Calibration → Board**, enter the measured dimensions and dictionary of
   the actual ChArUco print. Click **Update board**.
2. Add cameras and collect **Fitting captures** with varied board positions,
   distances, and tilts. Keep the board sharp and cover the image edges.
3. Click **Calibrate**, then collect separate **Validation captures** and click
   **Validate**. Follow the reported retry reasons.
4. Review **Results / history**, select passing cameras, and click **Apply selected**.
   Wait for **Applied** before using the result.
5. For standalone work, use **System → Download calibration results**. Copy the
   matching record into the camera's `calibration` field and set its `binding_id`
   before deployment.

Intrinsic calibration does not measure the mount. Recalibrate after replacement,
focus changes, or incompatible optical modes. Use history to restore compatible
calibration records.

## Check on hardware

Before enabling robot fusion, verify measured mounts, calibration, capture
timestamps, field accuracy, multi-camera load, and disconnect/restart recovery.
A passing software test or health check does not establish physical accuracy.
