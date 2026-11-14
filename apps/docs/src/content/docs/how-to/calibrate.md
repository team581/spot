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
4. Move the board slowly in front of the camera at varied distances and tilts.
   Spot captures a view each time the board has moved enough and shows part of the image that needs more views.
   Captured corners show as yellow dots, which turn green once their area has views at enough distances and tilts.
   Keep going until most dots are green, including near the image's edges and corners, where distortion is strongest.
5. Choose **Solve**. This pauses capture.
   - **Calibration ready**: choose **Apply**.
   - **Calibration error is too high**: choose **Resume capture**, capture more sharp views, and solve again.
     Spot drops outlier views once on its own, so a few bad captures are fine.
6. [Copy the change into `spot.toml`](../save-dashboard-changes/).
