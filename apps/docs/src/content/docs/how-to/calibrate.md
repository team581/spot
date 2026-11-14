---
title: Calibrate a camera
description: Calibrate a camera with a ChArUco board from the dashboard.
---

Calibrate each camera once per resolution, and again after changing its lens or focus.

1. On **Calibration**, enter your board's square counts, measured square and marker sizes, and dictionary.
   Check that the preview matches your board, then choose **Save board**.
2. Choose the camera.
   Check that the mode shown next to it is the one it will run in.
3. Choose **Start calibrating**.
4. Capture at least 12 views with **Capture view**, at varied distances and tilts, until no shaded area remains.
   Cover the image's edges and corners; that's where distortion is strongest.
   Hold the board still for each capture.
5. Choose **Solve**.
   - **Calibration ready**: choose **Apply**.
   - **Calibration error is too high**: capture more sharp views and solve again.
     Spot drops outlier views once on its own, so a few bad captures are fine.
6. [Copy the change into `spot.toml`](../save-dashboard-changes/).
