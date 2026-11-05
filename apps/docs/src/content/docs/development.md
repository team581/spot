---
title: Development
---

Install [mise](https://mise.jdx.dev/), then run from the repository root:

```sh
mise install
mise run setup
mise run dev
```

The dashboard opens at <http://127.0.0.1:5815> with synthetic cameras.
Run `mise tasks` for available checks and build commands, and
`uv run --package spot-vision spot-vision --help` for service commands.

## Build and test

```sh
mise run format
mise run lint
mise run typecheck
mise run test
```

After frontend changes, run `pnpm --filter spot-dashboard build` to update the
bundle served by Python. `mise run check:application` also builds native geometry
diagnostics and smoke-tests an installed wheel; it requires a C++ compiler.
Run CUDA checks on the target Jetson.

For browser tests, install Chromium with
`pnpm --filter spot-dashboard exec playwright install chromium`, then run
`pnpm --filter spot-dashboard test:browser`.

## Edit documentation

The canonical guides live in `apps/docs/src/content/docs/`. Keep READMEs as
entry points, and use executable configuration and CLI help for option references.
Avoid duplicating those references or recording deployment status in guides.

Run `pnpm --filter spot-docs dev` to preview at <http://127.0.0.1:5814>.
`pnpm --filter spot-docs build` builds the hosted site; `pnpm build:jetson`
builds the same content under `/docs/` for the installed appliance.
Rebuild both the dashboard and Jetson docs before building a Python wheel.

Commit conventions are defined in
[hk.pkl](https://github.com/team581/spot-2026/blob/main/hk.pkl); releases are managed by
[Release Please](https://github.com/team581/spot-2026/blob/main/.github/workflows/release-please.yml).
