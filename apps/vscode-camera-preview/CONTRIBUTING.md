# Spot Camera Preview contributing

## Development

Run `pnpm install` at the repository root, then `pnpm build` and `pnpm test` here. Java export tests live in `offseason-2026/offseason-bot`. Vite+ bundles the typed shared renderer into the static webview script. The extension host is a CommonJS bundle targeting Node 20, compatible with the existing VS Code minimum.

To debug, launch VS Code with `--extensionDevelopmentPath` pointing at this directory after running `pnpm build`. Open `offseason-2026/offseason-bot` in the development window.

## Releases

Merge the Release Please PR to publish a new version. Review its generated changelog before merging; it is included in the public extension package. The workflow checks and packages the tagged source, attaches the VSIX to a draft GitHub release, publishes that release to lock its assets, and publishes the same VSIX to the VS Code Marketplace.

Release Please tracks the extension and its bundled `@spot/camera-viewer` renderer. Renderer releases also trigger an extension patch release. Neither package is published to npm.

To retry a failed publication, use **Actions → Release Please → Run workflow** with the existing `camera-preview-vX.Y.Z` tag. Published GitHub releases reuse their original VSIX; already-published Marketplace versions are skipped.

## Coordinate regression tests

`pnpm test` compares the actual Jetson dashboard geometry-form adapter and both shared-renderer modes against 26 positive/negative translation and rotation cases exported by real WPILib. It covers positive/negative pitch, roll and yaw, compound rotations, and ±90° pitch. The same numeric pitch has the same sign and direction in Java and Jetson inspection controls (positive down, negative up). The two paths must render identical camera geometry for equivalent poses.

Run `./gradlew :offseason-bot:test --tests frc.robot.vision.SpotCameraConventionTest` in `offseason-2026` when changing coordinate handling. It verifies the exporter results and world-axis directions against `offseason-bot/src/test/resources/spot-camera-conventions.json`. The JS tests use the matching cases in `test/fixtures/spot-camera-conventions.json`. If intentionally changing those conventions, review the emitted `offseason-bot/build/spot-camera-preview/convention-cases.json` before updating those fixtures and running the Java and JS tests. Do not update the fixtures solely to silence a failing test.
