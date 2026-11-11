---
title: Development
---

Install [mise](https://mise.jdx.dev/) and [Nix](https://nixos.org/download/). The
vision service links OpenCV, which the repository's Nix shell provides. From the
repository root:

```sh
mise install
mise run setup
mise run dev
```

Open the dashboard URL that Vite prints. The development service replays the synthetic
images in `apps/vision/tests/data/regression` as cameras (their serials are the file
names, such as `center`) and keeps its state in `.spot-dev/`. Name cameras on the
dashboard to start them.
Run `mise tasks` for available checks and
`cargo run --manifest-path apps/vision/Cargo.toml -- --help` for service commands.

## Build and test

```sh
mise run format
mise run lint
mise run typecheck
mise run test
```

The Rust tasks run Cargo inside `nix develop`. After changing HTTP API types or the
robot config, regenerate the TypeScript client and JSON Schema (inside `nix develop`):

```sh
pnpm --filter spot-dashboard generate:api
pnpm --filter spot-docs generate:schema
```

The Jetson build (`jetson` feature: NVJPG decoding and the CUDA detector) only builds
for `aarch64-linux` through Nix, for example on the Jetson with
`nix run .#deploy -- test`. Run hardware checks on the Jetson.

## Edit documentation

The canonical guides live in `apps/docs/src/content/docs/`. Keep READMEs as
entry points, and use executable configuration and CLI help for option references.
Avoid duplicating those references or recording deployment status in guides.

Run `pnpm --filter spot-docs dev` to preview at <http://127.0.0.1:5814>.
`pnpm --filter spot-docs build` builds the hosted site; `pnpm build:jetson`
builds the same content under `/docs/` for the installed appliance.

Commit conventions are defined in
[hk.pkl](https://github.com/team581/spot-2026/blob/main/hk.pkl); releases are managed by
[Release Please](https://github.com/team581/spot-2026/blob/main/.github/workflows/release-please.yml).
