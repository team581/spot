---
title: VS Code camera preview
---

Install **Spot Camera Preview** (`team581.spot-camera-preview`) from the VS Code
Marketplace. Open the robot project's `src/main/deploy/spot.toml` in a trusted
workspace; the preview opens beside it, or run **Spot: Preview Cameras** from the
editor title or the file's context menu. It shows the saved file, updates on save,
and keeps the last valid preview while the file has errors. Spot validates the full
[robot configuration](../../robot-config/); the preview only checks what it shows.

For each camera it shows the mount, selector, mode, controls, and calibrated
resolutions, and warns when the mode's resolution has no calibration. Mounts use the
[camera conventions](../cameras/#mount). Camera bodies and the drivebase are
schematic.

Opening automatically needs a TOML extension such as
[Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml),
which also checks the file against Spot's schema. Turn it off with
`spot.cameraPreview.autoOpen`.

To develop the extension, follow [repository setup](../../development/) and run
`pnpm --filter spot-camera-preview test`. After building, launch VS Code with
`--extensionDevelopmentPath` pointing at `apps/vscode-camera-preview`.
