---
title: Camera setup
---

## Connect

Open <http://spot.local> or the default maintenance address
<http://10.5.81.11>.

On **Network**, set the team number (Spot connects to `10.TE.AM.2`) or an
NetworkTables server address for a simulator or laptop. Ethernet addressing (DHCP
or static) changes as a trial: confirm it before the countdown ends or it rolls
back. The maintenance address always stays.

## Assign cameras

Each camera in [`spot.toml`](../../robot-config/) finds its physical camera by USB
`serial`. Cameras that ship with the same serial also need a `port`, the USB path
shown on the naming page (for example `1-2.2`); keep those cameras in the same
ports, or reflash them with unique serials. If cameras share a serial and no port
tells them apart, Spot reports `duplicate_serial` instead of guessing.

On the dashboard's camera naming page, pick a plugged-in camera and give it a name.
This creates an override (see [saved settings](#saved-settings)).

## Tune

On a camera's page, choose the mode and adjust exposure and gain while watching the
live view and detections. Unset controls use the camera's defaults. Prefer short,
manual exposures to limit motion blur.

## Mount

Measure each `mount` from the robot origin on the floor to the camera, in meters on
WPILib axes (+X forward, +Y left, +Z up); positive pitch points the lens down.

Check mounts in the **Field** view on the **Cameras** page. It needs the field layout from
robot code. Each camera draws its robot estimate in its own color, the camera on that robot
with an arrow out of the lens and a post out of the top, and lines to the tags it used.
With correct mounts and calibrations, the robots overlap. Drag to orbit, and scroll or use
W/S to zoom and A/D/Q/E to pan. The legend shows each camera's distance and
heading from the median estimate, and its height off the floor, which should be near zero.
A camera that disagrees has a wrong mount or calibration. Cameras without an estimate are
drawn on another camera's robot, or on a gray robot at midfield. The
[VS Code extension](../vscode-camera-preview/) previews mounts from `spot.toml`.

## Calibrate

1. Print the board from the **Calibration** page at 100% scale and measure a
   square. If it differs, set the measured size on the page before capturing.
2. Choose a camera at the mode it will run in and start a session. Spot outlines
   the board corners it finds.
3. Capture views at varied distances and tilts until the coverage hint fills the
   image, including its edges and corners. Keep the board flat and sharp.
4. Solve. Spot rejects outlier views once, refits, and accepts the result only if
   its RMS error is low enough.
5. Apply the result. It becomes an override for that camera and resolution.

Recalibrate after changing a lens, its focus, or the mode's resolution.

## Saved settings

Dashboard edits are overrides kept on the Jetson. They take priority over robot code
until robot code matches them, then Spot removes them. The **Config** page lists
every override against the robot value and shows the merged `spot.toml` to copy into
robot code.

## Recordings

Spot keeps a rolling buffer and saves MCAP recordings around each enable. On
**Recordings**, choose **Replay** to step through a recording in the Field view, with each
camera's images and tag outlines. Space plays and pauses. Recordings contain camera images,
tag detections, estimates, camera status, the effective configuration and field layout, and
service logs. Spot's estimates are also NetworkTables values, so robot logs that record
NetworkTables show them in AdvantageScope next to the rest of the robot's data.

## Check on hardware

Before trusting estimates, check measured mounts, calibration, timestamps against
other sensors, accuracy on the field, and recovery after disconnecting a camera.
A passing software test does not establish physical accuracy.
