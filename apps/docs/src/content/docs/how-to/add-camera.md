---
title: Add a camera
description: Assign a new camera, tune it, and set its mount.
---

1. Plug the camera into the Jetson.
2. On the **Cameras** page, choose **Assign devices**, enter a camera name, and choose **Assign**.
   Names may use letters, digits, `-`, and `_`; they appear in NetworkTables topics.
3. On the camera's page, set **Mode**, **Auto exposure**, **Exposure**, and **Gain** while watching the live view.
   Use manual exposure, as short as still detects tags at range, to limit motion blur.
4. [Calibrate the camera](../calibrate/) at the mode it will run in.
5. [Copy the dashboard changes into `spot.toml`](../save-dashboard-changes/).
6. In `spot.toml`, set the camera's `mount` from CAD or a tape measure, and set `required = true` if Spot shouldn't report `ready` without it.
   See [mount](../../reference/config/#mount) for axes and units.
7. Deploy robot code and [check the mount](#check-a-mount).

## Cameras with the same serial

Some cameras ship with identical serial numbers.
Spot then also matches them by USB port, and the **Devices** page fills in `port` for you.
Keep those cameras in the same Jetson ports, or reflash them with unique serials.

## Check a mount

The **Field** view on the **Cameras** page draws each camera's robot estimate.

1. Put the robot where several cameras can see tags.
2. Compare the robots in the **Field** view.
   With correct mounts and calibrations, they overlap.
3. Check the legend.
   Each camera's distance and heading from the median estimate should be small, and its height off the floor near zero.

A camera that disagrees with the rest has a wrong mount or calibration.
Fix it in `spot.toml`, deploy, and check again.
