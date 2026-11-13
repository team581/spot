---
title: Preview camera mounts in VS Code
description: Check spot.toml camera mounts in a 3D preview without a robot.
---

1. Install **Spot Camera Preview** (`team581.spot-camera-preview`) and **Even Better TOML** from the VS Code Marketplace.
2. Open the robot project as a trusted workspace.
3. Open `src/main/deploy/spot.toml`.
   The preview opens beside it.
   If it doesn't, run **Spot: Preview Cameras**.
4. Save the file to update the preview.

The preview warns when a camera's mode has no calibration.
While the file has errors, it keeps showing the last valid version.

To stop it opening on its own, turn off `spot.cameraPreview.autoOpen`.
