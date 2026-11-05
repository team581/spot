---
title: VS Code camera preview
---

Install **Spot Camera Preview** (`team581.spot-camera-preview`) from the VS Code
Marketplace. Open `VisionConfig.java` in a trusted workspace and run
**Spot: Preview Cameras** from the Command Palette or the editor's camera icon.

The project needs a Gradle wrapper, Java toolchain, and an
`exportSpotCameraPreview` task that writes `build/spot-camera-preview/profile.json`.
Save Java changes to rebuild the preview; check **Build output** if it stays stale.

Positions use the [camera geometry conventions](../cameras/#geometry).
The rendered camera bodies and drivebase are schematic.

To develop the extension, follow [repository setup](../../development/) and run
`pnpm --filter spot-camera-preview test`. After building, launch VS Code with
`--extensionDevelopmentPath` pointing at `apps/vscode-camera-preview`.
