---
title: Work on Spot
description: Run Spot locally, check changes, and test builds on hardware.
---

## Set up

The vision service requires OpenCV 5.1 or newer, found with pkg-config as `opencv5`.

On macOS, install it with [Homebrew](https://brew.sh/) from the repository root:

```sh
brew bundle
```

Then install [mise](https://mise.jdx.dev/) and run from the repository root:

```sh
mise install
mise run setup
```

## Run locally

```sh
mise run dev
```

Open the URL Vite prints.
The service treats each image in `apps/vision/tests/data/regression` as a camera, with the file name as its serial (for example, `center`).
Assign them on the dashboard to start them.
State is kept in `.spot-dev/`; delete it to start over.

To run the dashboard against a real Jetson instead:

```sh
mise run dev:jetson
```

## Check a change

```sh
mise run format:fix
mise run lint
mise run typecheck
mise run test
```

## Change the HTTP API or `spot.toml` format

Regenerate the TypeScript client and the config schema:

```sh
pnpm --filter spot-dashboard generate:api
pnpm --filter spot-docs generate:schema
```

CI fails if these are stale.

## Change a NetworkTables struct

Change `apps/vision/src/structs.rs` and the matching class in `packages/java-client` together.
The Java client's tests check that they agree.

## Try the Java client in robot code

1. Publish it to WPILib's local Maven repository:

   ```sh
   ./gradlew publishAllPublicationsToWpilibRepository
   ```

2. Copy `apps/docs/public/vendordep.json` to the robot project's `vendordeps/Spot.json`.

## Test on a Jetson

The GPU build only builds for `aarch64-linux`, so test hardware changes by [deploying to a Jetson](../update/).

## Edit the docs

```sh
pnpm --filter spot-docs dev
```

The preview runs at <http://127.0.0.1:5814>.
Pages are in `apps/docs/src/content/docs/`, sorted into how-to guides, reference, and explanation.

## Work on the VS Code extension

```sh
pnpm --filter spot-camera-preview build
code --extensionDevelopmentPath="$PWD/apps/vscode-camera-preview"
```
