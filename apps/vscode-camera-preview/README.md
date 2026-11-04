# Spot Camera Preview

Preview Spot robot camera mounts beside `VisionConfig.java`. Inspect camera positions and orientations in a 3D view, then save Java changes to refresh the scene. The preview runs offline without a connection to the robot.

## Install

Search for **Spot Camera Preview** (`team581.spot-camera-preview`) in the VS Code Extensions view and click **Install**. Leave automatic updates enabled to receive new versions. If you previously installed a VSIX, enable **Auto Update** in the extension's menu.

## Open your camera configuration

1. Open your Spot robot project in a trusted VS Code workspace.
2. Open `VisionConfig.java`. For Team 581's `offseason-2026` project, this is `offseason-bot/src/main/java/frc/robot/vision/VisionConfig.java`.
3. Click the camera icon in the editor title bar, or run **Spot: Preview Cameras** from the Command Palette.
4. Register your camera mounts in **CAMERAS**, then save changes to rebuild and refresh the preview.

The preview reads your compiled Java configuration. Your project's Gradle wrapper and Java toolchain must be available. The first build may need network access to download dependencies.

## Inspect mounts

- Select a camera to inspect its position, orientation, and local axes.
- Hide cameras to isolate a mount.
- Drag to orbit and scroll to zoom. Use **Top**, **Front**, **Side**, or **Reset** to change the view.
- Enable **Show drivebase** to compare mounts against a robot footprint. Adjust its length and width in inches; these preview settings do not change your robot configuration.

Positions use metres and WPILib NWU axes. Positive pitch points the lens down; negative pitch points it up. Image rotation is separate from mount rotation.

The drivebase defaults to 30 × 30 inches, centered on the robot origin. Camera bodies and the drivebase are schematic.

## Automatic opening and refresh

The preview normally opens when you open `VisionConfig.java`. Disable **Spot Camera Preview: Auto Open** (`spot.cameraPreview.autoOpen`) in Settings to open it manually instead.

Save Java changes to rebuild the camera configuration and refresh the scene. Unsaved changes are not shown. If a build fails, the preview keeps the last successful scene; open **Build output**, fix the error, then save or refresh.

## Troubleshooting

- **The preview does not open:** confirm that the workspace is trusted, then run **Spot: Preview Cameras**. Closing the panel suppresses automatic opening for the rest of that session.
- **The scene is empty:** check that your camera mounts are registered in **CAMERAS**. A named constant alone does not appear in the scene.
- **The preview is stale:** open **Build output** and resolve any Java or Gradle errors. Save your changes or refresh to retry.
