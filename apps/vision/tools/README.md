# Vision diagnostics and development tools

The installed dashboard is the supported UI for live preview, camera naming,
tuning, calibration, networking, and support exports. Its operator guides ship
at `/docs/` and live in [`apps/docs`](../../docs/src/content/docs/index.md).
The old alpha/prototype web servers, calibration wizard, and SSH launcher have
been retired; historical evidence may still refer to them.

## Headless camera and recording diagnostics

Run these from the repository root after `mise run setup` (CPU) or
the [NixOS package](../../../nix/README.md) (CUDA). Supply the relevant configuration and camera ID:

```sh
uv run --no-sync spot-vision camera-modes --config apps/vision/config/spot.json --camera 1
uv run --no-sync spot-vision probe --config apps/vision/config/spot.json --camera 1 --frames 100
uv run --no-sync spot-vision replay --config apps/vision/config/spot.json --camera 1 --input recording.mp4
uv run --no-sync spot-vision benchmark --config apps/vision/config/spot.json --camera 1 --input recording.mp4
```

`compare`, `image-regression`, `validate-calibration`, and `calibrate-charuco`
provide recording comparisons, fixed-image checks, and offline calibration.
Use `spot-vision COMMAND --help` for options. These config-file diagnostics are
separate from the installed application's robot-owned v2 profiles.

## Bench evidence

`bench_capture.py` collects bounded status samples from the installed service.
It does not change settings, restart services, or create a capture owner:

```sh
uv run --no-sync python apps/vision/tools/bench_capture.py \
  --output /tmp/spot-bench --duration-s 30 --port 5800
```

On the Jetson, `--tegrastats` also records system telemetry. The output directory
must not already exist.

`bench_session.py` records run metadata, collects explicitly selected remote
files using scp, analyzes exported robot logs, and compares reports. It does
not tune cameras or certify hardware. Use its `new-run`, `collect`, `doctor`,
`report`, and `compare` subcommands:

```sh
uv run --no-sync python apps/vision/tools/bench_session.py --help
```

Follow the [robot integration session](../../docs/src/content/docs/operator/robot-integration-session.md)
for topology, measurement context, and remaining physical checks. Keep captures
and reports outside tracked source; `/bench-runs/` is ignored by Git.

## Dashboard development without hardware

```sh
uv run --no-sync python apps/vision/tools/beta_ui_fixture.py --port 5808
pnpm --filter spot-dashboard dev
```

The fixture supplies synthetic cameras to the real HTTP boundary. See the
[dashboard guide](../../dashboard/README.md) for browser tests and architecture.

## Fixtures and documentation

`generate_beta_fixtures.py` regenerates synthetic WPILib struct packets used by
Python and Java tests. See the [transport guide](../../../docs/NetworkTables.md) before changing
schemas or golden packets; these fixtures are not measured hardware evidence.

### Operator documentation

The guides in `apps/docs/src/content/docs/` are published by Astro/Starlight and
bundled with the installed application. Edit those guides to update both sites.
Run `pnpm build && pnpm build:jetson` before building a wheel so `dist/dashboard/`
and `dist/jetson-docs/` accompany the source checkout.

## Local verification

```sh
mise run check:application
mise run test
pnpm --filter spot-dashboard test:browser
```

The application check includes Python format/lint/types, unit and integration
tests, a CPU wheel build, and isolated installed-service verification. CUDA and
live camera/network acceptance still require the Jetson.
