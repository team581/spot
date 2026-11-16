# Spot Camera Preview

See where each camera sits on your robot and which way it points, without a robot or a Jetson.

[Spot](https://spot.frc581.com) is Team 581's AprilTag vision system for FRC robots.
A robot project lists its cameras in `src/main/deploy/spot.toml`, and this extension draws them in 3D so you can check a mount before you deploy.

## Features

- Opens beside `spot.toml` when you open the file
- Updates each time you save
- Shows errors in the file while keeping the last valid cameras on screen
- Warns when a camera's `mode` has no calibration

## Usage

1. Open your robot project as a trusted workspace.
2. Open `src/main/deploy/spot.toml`.
   The preview opens beside it.
3. Edit a camera mount and save.
   The preview updates.

To reopen a closed preview, run **Spot: Preview Cameras** from the Command Palette, click the camera icon in the editor title bar, or right-click `spot.toml` in the Explorer.

Install [Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml) to check and complete `spot.toml` keys as you type.
This extension gives it the Spot schema, so you don't need a `#:schema` line.

## Settings

| Setting                       | Default | Description                                        |
| ----------------------------- | ------- | -------------------------------------------------- |
| `spot.cameraPreview.autoOpen` | `true`  | Open the camera preview when `spot.toml` is opened |

## Learn more

- [Preview camera mounts in VS Code](https://spot.frc581.com/how-to/preview-mounts-in-vscode/)
- [Add a camera](https://spot.frc581.com/how-to/add-camera/)
- [`spot.toml` reference](https://spot.frc581.com/reference/config/)
