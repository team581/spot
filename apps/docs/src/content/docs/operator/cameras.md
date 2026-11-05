---
title: Camera setup
---

## Connect

Open <http://spot.local:5800> or the default maintenance address
<http://192.168.69.170:5800>. For direct Ethernet, give the laptop
`192.168.69.171/24`. The Network page shows current addresses and the robot link.

Fresh images request a DHCP address and also keep the maintenance address.
Use **Network → Connection** to set the NetworkTables robot endpoint: a team
number, or a server address for an NT4 server on a laptop or simulator. It
reconnects immediately and saves the selection across reboots.
Changing the endpoint does not change a static Jetson IP address.

Use **Network → Jetson address** to change Ethernet settings. Check the new
connection and click **Keep settings** before the trial expires; an unconfirmed
trial rolls back. Both Ethernet ports share one network.

Camera settings can be adjusted while the robot is enabled or disconnected. Spot
keeps the last robot configuration it received, so bench work only needs robot code
to have connected once.

## Assign cameras

Camera names come from robot code. Select a physical feed, confirm it matches the
camera, then assign an available code-defined name. Unnamed cameras are preview-only;
name a camera before tuning or calibrating it.

## Mount

Measure mounts from the robot origin to the camera optical origin in metres,
using WPILib axes: X forward, Y left, Z up. Positive pitch points the lens down.
Mounts come from robot code. On the camera's **Mount** tab, use **Inspection
preview** to adjust a mount, then **Save mount on Spot**. The saved mount is used by
both Spot and robot localization and appears in **Changes** until robot code matches
it or it is reverted.
The [VS Code extension](../vscode-camera-preview/) previews deployed mounts.

## Tune

Use the camera page's live preview and detection outlines while adjusting exposure
and gain. Undo, redo, and reset controls let you compare settings.

## Saved settings

Robot code supplies defaults in `src/main/deploy/spot-config.json`. Edits made on
Spot take priority and persist across reconnects, restarts, and deployments.
**Changes** lists each edit next to its robot-code value, flags edits whose
robot-code value changed later, and reverts them individually or together. Edited
camera controls also show their robot-code value on the camera page. Robot code can
read the edited paths from the `/Spot/overrides` NetworkTables topic.

To keep edits, use **Changes → Copy spot-config.json** (or download it), replace the
file in the robot project, and deploy. Edits that match the deployed values are
removed automatically.

## Calibrate

1. In **Calibration → Board**, enter the measured dimensions and dictionary of
   the actual ChArUco print. Click **Update board**.
2. Add cameras and collect **Fitting captures** with varied board positions,
   distances, and tilts. Keep the board sharp and cover the image edges.
3. Click **Calibrate**, then collect separate **Validation captures** and click
   **Validate**. Follow the reported retry reasons.
4. Review **Results / history**, select passing cameras, and click **Apply selected**.
   Wait for **Applied** before using the result.
5. Applied calibrations appear in **Changes**; adopt them in robot code like other
   edits.

Intrinsic calibration does not measure the mount. Recalibrate after replacement,
focus changes, or incompatible optical modes. Use history to restore compatible
calibration records. **Export calibrations** and **Import calibrations** under
history move calibration records between Spots.

## Check on hardware

Before enabling robot fusion, verify measured mounts, calibration, capture
timestamps, field accuracy, multi-camera load, and disconnect/restart recovery.
A passing software test or health check does not establish physical accuracy.
