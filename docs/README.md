# Spot documentation

Current setup and operating instructions live in the application guides. The
plans, design references, and dated evidence in this directory explain earlier
decisions and verification checkpoints.

## Current guides

- [Repository setup](../README.md): uv/pnpm workspace, native builds, and local checks.
- [Operator guide](../apps/docs/src/content/docs/index.md): the installed dashboard,
  camera setup, calibration, and recovery. These same pages ship in the dashboard's
  offline **Docs** site.
- [Robot integration session](../apps/docs/src/content/docs/operator/robot-integration-session.md):
  the October 18–19 commissioning record, measured settings, and remaining checks.
- [Dashboard development](../apps/dashboard/README.md): React/TypeScript structure,
  Vite+ development, and browser verification.
- [Vision tools](../apps/vision/tools/README.md): headless camera diagnostics and recording tools.

Use dated hardware evidence for the configuration and trial it records. A passing
local suite, a live preview, or an older deployment report does not establish the
remaining camera, timing, accuracy, endurance, or fusion acceptance gates.

## Supported runtime and tools

The installed dashboard is the operator UI. Diagnostic commands remain available
without bringing back the old alpha/prototype web servers.

| Entry point                                           | Owner and purpose                                                                                                                                                                                                                                            |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `spot-vision run`                                     | [`app.py`](../apps/vision/src/spot_vision/app.py), the installed application selected by the systemd service. The compiled [dashboard](../apps/dashboard/README.md) uses its API and shared frames. Robot profiles and durable configuration govern changes. |
| `spot-vision probe`, `replay`, `compare`, `benchmark` | Headless camera or recording-based CLI diagnostics.                                                                                                                                                                                                          |
| `spot-vision calibrate-charuco`                       | Headless calibration from a directory of captured images. Live operator calibration uses the installed dashboard.                                                                                                                                            |
| `apps/vision/tools/bench_capture.py`                  | Bounded observations and session records for the installed application and robot integration.                                                                                                                                                                |

The old alpha viewer, standalone calibration wizard, prototype HTTP server, and
`probe_dashboard.py` SSH/terminal launcher have been retired. Historical reports
may name those files and commands; use the current operator guides for new work.
Their deletion does not change the installed service's SSH authentication or
system network configuration.

## Historical requirements and evidence

- [Original system specification](Vision%20Solution%20%28Spot%29%20Specs.md) and
  [research notes](Vision%20Solution%20%28Spot%29%20Notes.md): initial design context.
- [Original Spot plan](Spot%20Robot%20Integration%20Plan.md) and
  [October 11 integration simplification](Offseason%20Spot%20Integration%20Simplification%20Plan.md):
  architecture and protocol decisions. The latter supersedes the shared/hybrid
  robot architecture in the former.
- [October 8 project status](history/2026-10-08-project-status.md),
  [October 11 implementation status](Implementation%20Status.md), and
  [integration results](Offseason%20Spot%20Integration%20Results.md): dated checkpoints,
  not a live description of the current checkout or device.
- [Alpha verification](Alpha%20Verification.md),
  [Spot software verification](verification/Software%20Verification.md), and
  [hardware qualification checklist](verification/Hardware%20Qualification.md):
  retained evidence and explicitly unperformed trials.
- [Original GUI design in Penpot](https://design.penpot.app/#/workspace?team-id=3e981c57-46d6-803d-8008-be904f2a7c48&file-id=fd558256-f8c8-8184-8008-c139acc14eb0&page-id=fd558256-f8c8-8184-8008-c139acc14eb1): historical revision 3 mockups.
  [Dated comparison evidence](verification/Visual%20Comparisons.html) retains
  the inspected native exports and actual fixture captures. Current application
  code and tests live in `apps/dashboard`; the old editable mockup generators and
  portable reference exports have been removed.

Keep new command instructions in the relevant application guide. Keep measured
results in a dated record with the tested revision, configuration, and limitations;
avoid updating old counts or deployment claims to describe a later checkout.
