---
title: VS Code camera preview
---

Install **Spot Camera Preview** (`team581.spot-camera-preview`) from the VS Code
Marketplace. Open the robot project's `src/main/deploy/spot-config.json` (or
`VisionConfig.java`) in a trusted workspace and run **Spot: Preview Cameras** from
the Command Palette or the editor's camera icon. The preview reads the
[robot configuration](../../robot-config/) directly and updates when the file is
saved; no build is needed.

Positions use the [camera geometry conventions](../cameras/#mount).
The rendered camera bodies and drivebase are schematic.

To develop the extension, follow [repository setup](../../development/) and run
`pnpm --filter spot-camera-preview test`. After building, launch VS Code with
`--extensionDevelopmentPath` pointing at `apps/vscode-camera-preview`.
