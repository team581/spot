# Spot Camera Preview

Private Team 581 VS Code extension. Open `VisionConfig.java` for a split-screen view of the actual compiled camera mounts. Save Java changes to refresh. Use the camera icon or **Spot: Preview Cameras** to reopen a closed preview.

See the [student guide](https://github.com/team581/spot-2026/blob/main/apps/docs/src/content/docs/operator/vscode-camera-preview.md) for VSIX installation, coordinate conventions, and troubleshooting.

## Development

Run `pnpm install` at the repository root, then `pnpm build` and `pnpm test` here. Java export tests live in `offseason-2026/offseason-bot`. Vite+ bundles the typed shared renderer into the static webview script. The extension host is a CommonJS bundle targeting Node 20, compatible with the existing VS Code minimum.

To debug, launch VS Code with `--extensionDevelopmentPath` pointing at this directory after running `pnpm build`. Open `offseason-2026/offseason-bot` in the development window.

## Private release procedure

1. Set the extension version in `package.json`; run tests and `pnpm package`.
2. Authenticate GitHub CLI with access to the private Spot repository.
3. Run `node release.cjs` to publish the versioned VSIX to the private repository. Users download it from [Spot releases](https://github.com/team581/spot-2026/releases) and install it through **Extensions → … → Install from VSIX…**. Updates use the same steps.

## Coordinate regression tests

`pnpm test` compares the actual Jetson dashboard geometry-form adapter and both shared-renderer modes against 26 positive/negative translation and rotation cases exported by real WPILib. It covers positive/negative pitch, roll and yaw, compound rotations, and ±90° pitch. The same numeric pitch has the same sign and direction in Java and Jetson inspection controls (positive down, negative up). The two paths must render identical camera geometry for equivalent poses.

Run `./gradlew :offseason-bot:test --tests frc.robot.vision.SpotCameraConventionTest` in `offseason-2026` when changing coordinate handling. It verifies the exporter results and world-axis directions against `offseason-bot/src/test/resources/spot-camera-conventions.json`. The JS tests use the matching cases in `test/fixtures/spot-camera-conventions.json`. If intentionally changing those conventions, review the emitted `offseason-bot/build/spot-camera-preview/convention-cases.json` before updating those fixtures and running the Java and JS tests. Do not update the fixtures solely to silence a failing test.

Drivebase visibility and dimensions are local preview settings. The footprint defaults to 30 inches square, centered on the robot origin, with length along +X and width along +Y.
