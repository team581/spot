# Spot Camera Preview

Private Team 581 VS Code extension. Open `VisionConfig.java` for a split-screen view of the actual compiled camera mounts. Save Java changes to refresh. Use the camera icon or **Spot: Preview Cameras** to reopen a closed preview.

See the [student guide](https://github.com/team581/spot-2026/blob/main/apps/docs/src/content/docs/operator/vscode-camera-preview.md) for installation, automatic updates, coordinate conventions, and troubleshooting.

## Development

Run `pnpm install` at the repository root, then `pnpm build` and `pnpm test` here. Run `python3 test/installer.py` from this directory to exercise the Gradle installer with fake editor/release commands. Java export tests live in both robot projects. The shared renderer is copied from `@spot/camera-viewer` during `pnpm package`.

To debug, launch VS Code with `--extensionDevelopmentPath` pointing at this directory after compiling and copying `../../packages/camera-viewer/viewer.js` into `media/viewer.js` (packaging does this automatically). Open one of the supported robot projects in the development window.

## Private release procedure

1. Set the extension version in `package.json`; run tests and `pnpm package`.
2. Authenticate GitHub CLI with access to the private Spot repository.
3. Run `node release.cjs`. It verifies repository privacy, publishes the versioned VSIX and checksum, and pins both local robot-project manifests. It does not commit or push repository changes.
4. Commit the implementation and updated manifests in both repositories so students obtain the approved release pin when pulling changes. A release alone does not advance student installations.

The installer checks the approved version on normal robot builds, downloads a missing package through GitHub CLI, verifies SHA-256, and invokes VS Code's installation CLI. No Marketplace entry is used. Installation warnings do not fail a robot build; the explicit installation task fails on errors. A cached package can install offline.

The first release may refer to a repository commit predating the extension source. Release assets are the versioned distribution; commit and push the accompanying source changes as part of rollout.

## Coordinate regression tests

`pnpm test` compares the actual Jetson dashboard geometry-form adapter and both shared-renderer modes against 26 positive/negative translation and rotation cases exported by real WPILib. It covers positive/negative pitch, roll and yaw, compound rotations, and ±90° pitch. The same numeric pitch has the same sign and direction in Java and Jetson inspection controls (positive down, negative up). The two paths must render identical camera geometry for equivalent poses.

Run `SpotCameraConventionTest` in both robot projects when changing coordinate handling. It verifies their exporter results and world-axis directions against the fixtures in `src/test/resources/spot-camera-conventions.json`. If intentionally changing those conventions, review the emitted `build/spot-camera-preview/convention-cases.json` before updating both fixtures and running the JS tests. Do not update the fixtures solely to silence a failing test.

Drivebase visibility and dimensions are local preview settings. The footprint defaults to 30 inches square, centered on the robot origin, with length along +X and width along +Y.
