# Dashboard

The operator dashboard is a React/TypeScript app built with Vite+. Python serves
its compiled static files alongside the offline docs. The installed service needs
no Node process, CDN, network font, or frontend development dependency.

From the repository root:

```sh
mise run setup
pnpm --filter spot-dashboard dev
```

The development server runs at <http://127.0.0.1:5815>. API and docs requests proxy
to `http://127.0.0.1:5808`; set `SPOT_BACKEND` to use another backend. The proxy
rewrites Host and Origin together for the backend's existing same-origin checks.
Production requests go directly to Python and keep its session/CSRF protection.

For synthetic cameras without hardware, run this in another terminal:

```sh
uv run --no-sync python apps/vision/tools/beta_ui_fixture.py --port 5808
```

## Code ownership

- `src/pages/` owns route UI and page-specific form drafts. Hash URLs are stable.
- `src/components/` owns reusable camera feeds, detections, geometry, and controls.
- `src/api.ts` owns HTTP errors, CSRF, request IDs, and acknowledged operation jobs.
- `src/dashboard.tsx` owns the browser session and status polling.
- `src/state/` owns numeric editing, serialized tuning, acknowledged undo/redo, and theme preferences.
- `src/previews.ts` owns the bounded preview scheduler, paused snapshots, and bitmap disposal.
- `src/types.ts` describes the Python snapshots consumed by the UI.
- `src/styles/` owns theme tokens, page styles, and responsive layout. Fonts use the system stack.

The shared renderer remains in `packages/camera-viewer`, also used by the VS Code
extension. Geometry inspection edits a local preview; production transforms stay
pinned by robot code. Configuration writes keep the service's revision checks.

## Verification

```sh
pnpm --filter spot-dashboard check
pnpm --filter spot-dashboard test
pnpm --filter spot-dashboard build
pnpm --filter spot-dashboard exec playwright install chromium
pnpm --filter spot-dashboard test:browser
```

Vitest covers editing/history, geometry conventions, operation acknowledgements,
and preview lifecycle. The legacy alpha GUI tools and their HTML-extraction tests have been retired.
Playwright serves `dist/dashboard` through the real Python HTTP boundary with
synthetic cameras. It exercises navigation, sessions, tuning, calibration, locks,
network confirmation/rollback, stale frames, downloads, and imports. Some failure
and network scenarios intercept API responses; no tests change a machine's network.
`SPOT_DASHBOARD_ASSETS` can point the browser suite at another built asset directory.

Run `pnpm build && pnpm build:jetson` before `mise run check:application` or a wheel
build. CMake requires `dist/dashboard` and `dist/jetson-docs`, installs both, and
bundles the emitted files in the application package. Python integration tests fetch
every installed JS/CSS chunk from a different working directory. CI runs these
checks and the browser suite. Camera hardware, CUDA, and live Ethernet changes
remain Jetson acceptance checks.
