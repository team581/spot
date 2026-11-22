---
title: Add a camera
description: Assign a new camera, tune it, and set its mount.
---

1. Plug the camera into the Jetson. For three or more Swyft cameras, [split them across USB ports](#wire-multiple-swyft-cameras).
2. On the **Cameras** page, choose **Assign devices**, enter a camera name, and choose **Assign**.
   Names may use letters, digits, `-`, and `_`; they appear in NetworkTables topics.
3. On the camera's page, set **Mode**, **Auto exposure**, **Exposure**, and **Gain** while watching the live view.
   Use manual exposure, as short as still detects tags at range, to limit motion blur.
4. [Calibrate the camera](../calibrate/) at the mode it will run in.
5. [Copy the dashboard changes into `spot.toml`](../save-dashboard-changes/).
6. In `spot.toml`, set the camera's `mount` from CAD or a tape measure, and set `required = true` if Spot shouldn't report `ready` without it.
   See [mount](../../reference/config/#mount) for axes and units.
7. Deploy robot code and [check the mount](#check-a-mount).

## Wire multiple Swyft cameras

Use this layout as a starting point for 1280×800 at 120 FPS on the J401.

| Cameras | Four USB-A sockets (J17/J18) | Two USB-A sockets (J7) | USB-C Host/DP (J19) |
| ------: | ---------------------------: | ---------------------: | ------------------: |
|       3 |                            2 |                      1 |                   0 |
|       4 |                            2 |                      2 |                   0 |
|       5 |                            2 |                      2 |                   1 |

Use any two sockets in the four-port block. For J7, try the lone USB-A stack beside the camera expansion connector and confirm it in the USB tree below.
For J19, use a USB-C data cable or a USB-C to USB-A data adapter with the Swyft cable. Leave the [Debug/Recovery port](../../reference/jetson/#debug-port) free.

1. Run `lsusb -t` on the Jetson. All Swyfts should show `480M`. Only two should appear under the Microchip hub. J7 cameras should appear under the Renesas controller (`xhci_hcd`). The J19 camera should appear directly under the Jetson's `tegra-xusb` root hub, on a different root port from the Microchip hub.
2. Stream all cameras together at the intended settings with tags in view. On **System** → **Cameras**, check that **Capture FPS** reaches the target, **FPS** keeps up, and **Dropped frames** don't steadily increase.
3. If a stream won't start, check `sudo journalctl -k -b` for `Not enough bandwidth`. See [why cameras share USB bandwidth](../../explanation/usb-camera-bandwidth/) for alternatives.

## Cameras with the same serial

Some cameras ship with identical serial numbers.
Spot then also matches them by USB port, and the **Devices** page fills in `port` for you.
Keep those cameras in the same Jetson ports, or give them unique serials.

To give a Swyft USB camera a unique serial:

1. On the **Devices** page, choose **Set serial** next to the camera's serial.
2. Enter the new serial, using letters and digits, and choose **Write**.
3. Replug the camera.
4. Assign the camera again.
   Spot drops its `port`, since the serial alone now identifies it.

Other cameras need their maker's tool.

## Check a mount

The **Field** view on the **Cameras** page draws each camera's robot estimate.

1. Put the robot where several cameras can see tags.
2. Compare the robots in the **Field** view.
   With correct mounts and calibrations, they overlap.
3. Check the legend.
   Each camera's distance and heading from the median estimate should be small, and its height off the floor near zero.

A camera that disagrees with the rest has a wrong mount or calibration.
Fix it in `spot.toml`, deploy, and check again.
