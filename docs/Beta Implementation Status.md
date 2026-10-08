# Beta implementation and qualification

Contract: [Spot Beta Robot Integration Plan](Spot%20Beta%20Robot%20Integration%20Plan.md),
October 7, 2026. This file tracks evidence; it does not change the contract.

Updated October 8, 2026. The user authorized **software implementation now;
defer hardware qualification**. Software implementation is complete within that
scope. This is not a robot-ready or hardware acceptance declaration.

[Software verification](beta-verification/Software%20Verification.md) contains
test results, installed-artifact identity, GUI comparisons and review evidence.
[Deferred hardware qualification](beta-verification/Hardware%20Qualification.md)
lists the remaining measured trials without changing their budgets.

## Implementation stages

| Stage | Status | Evidence |
| --- | --- | --- |
| Protocol, configuration and clock fixtures | Software verified | Separate v2 topics/schema; Python/Java serialized fixtures, bounded packets, capture/connection/sync epochs and current-exchange clock gates |
| Device discovery and durable state | Software verified; physical trials deferred | Stable serial/topology identity, capability/readback checks, immutable transactional generations, last-known-good recovery, cached code profiles and replacement binding |
| Installed web and calibration | Software verified; hardware load trials deferred | All routes and local assets; Penpot revision 3 light/dark/Auto comparisons; live acknowledged tuning/concurrency; shared-frame independent fit/holdout calibration and atomic group activation/restore |
| Shared robot integration | Software verified | Reusable `shared` IO/processor/owned queue/diagnostics and Limelight adapter; 12 Java contract tests; offseason, competition and new-member robot projects compile |
| Robot shadow qualification | Not performed | Actual roboRIO timing, measured mounts and surveyed trials required |
| Controlled fusion | Not performed | Requires disabled robot, measured mounts and passing shadow evidence |
| Operator handoff | Software delivered; student hardware trial deferred | Offline ordered guide, compiled two-robot Java example, immutable release verification, activation/rollback tools and explicit qualification checklist |

## Verification checkpoint

- Source Python suite: **421 passed**. Final isolated installed wheel: **421 passed**.
- JavaScript state/theme and retained alpha tuning/viewer suites: **17 passed**.
- Java contract suite: **12 passed**, with all three robot projects compiled.
- Existing offseason robot regression suite: **24 passed**.
- CPU Mac release **`dd447aa1719e28d1`** verified against its native module and
  application hashes. Its installed no-camera/no-NT health endpoint responded in
  **0.806 s** in one smoke run. This is not a cold/warm target-hardware percentile.
- Actual CUDA, USB modes/cadence, independent FPGA timing, accuracy, endurance,
  physical recovery, power-loss trials and student hardware handoff remain
  unperformed. Offseason camera definitions are deliberately empty until measured
  mounts are supplied. Fusion, heading and revised trust remain off.

## Qualification restrictions

Beta is not robot-ready until the hardware gates in Section 13 pass. CPU tests do
not certify CUDA, NT simulation does not certify FPGA timing, and preview liveness
does not certify four-camera throughput or pose accuracy. Do not invent offseason
mounts, alter placeholder Limelights, lower acceptance budgets, or activate fusion
to make these gates appear complete.

Existing local changes in both checkouts are retained. The alpha verification
report remains historical evidence.
