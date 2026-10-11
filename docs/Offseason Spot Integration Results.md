# Offseason Spot integration results

Software integrated locally on October 11, 2026, in Spot and the sibling
`offseason-2026` checkout. Production camera commissioning and robot qualification
remain open. Nothing was deployed; changes remain available for review.

## Baselines and boundary

| Checkout | Starting revision | Initial working changes |
|---|---|---|
| Spot `main` | `7b1b1ee9409d9684683aaee5b662e7047042594b` | Supplied simplification plan, untracked |
| Robot `spot-beta-integration` | `55ce1972a232d6c813ca500bf9521a2032a40f56` | Clean |
| Robot accepted scheduler baseline | `origin/main`, `e429b593dea671732e311ca453afddca22aa32c6` | Two existing scheduler implementations copied unchanged |

The accepted sorted-list implementations are `SubsystemExecutionSequencer` and
`StateMachineSubsystemInputManager`. No other baseline changes were merged.
A fresh temporary Java process registered stateless probes in deliberately mixed
order and exercised the production scheduler. Its independently asserted trace:

```text
inputs:  imu → vision → localization → health → manager
actions: manager → health → localization → vision → imu
```

The trace used production priority values (10, 11, 12, 28, 29). It did not tick
an accumulated set of subsystem test fixtures, add Gradle tasks or add a
persistent diagnostic entrypoint.

## Implementation

All Spot production code, generated Java bindings, immutable results and the
local trust model now live under `offseason-bot/src/main/java/frc/robot/vision/`.
Contract tests, the compiled example and golden resources moved to offseason
sources. Shared Spot helpers, the Limelight adapter and offseason Limelight
hardware/classes were removed. Pre-existing shared trust, results and camera
utilities remain unchanged. The branch-added competition empty-results guard
and shared protobuf build changes are absent relative to the integration merge
base. Protobuf 4.33.2 is an offseason implementation dependency.

`Vision` folds pipeline and diagnostics ownership into one subsystem. Its
single IO read takes one injected FPGA clock snapshot and explicit enabled
state; getters return cached immutable status. It owns bounded history, ordered
one-shot release, generation/reset/policy invalidation, shadow diagnostics and
camera faults. Lifetime rejection counters survive transient availability loss.
Fusion acknowledgement validates the delivered frame identity and cannot mark
a newer rejected frame fused. Marked extraction helpers retain the exact
migration comment, including regenerated Java; the formatter preserves it.

`Localization` owns one local `TrustFactor`, rechecks age and historical
availability for the entire batch before any estimator insertion, submits
immutable measurements in order, acknowledges actual submissions, then refreshes
its pose directly from the drivetrain. Physical chassis motion drives trust
degradation; corrected pose changes do not count as travel. The bounded penalty
history and conservative correlation accumulator keep split-batch outcomes equal
at a common observation time. Seeding is distinct from camera evidence; simulation
uses identical trust and health rules. Existing provisional thresholds remain.

Hub acquisition uses all four fixed camera roles, exact red/blue tag sets,
unknown-alliance broad acquisition and 0.5-second loss recovery. Repeated requests
are idempotent. The additive schema v2 policy uses current-session increasing
robot-state sequences, positive selection generations, sorted unique field IDs,
service support advertisement and applied-generation echo. Detection runs once;
only selected detections reach the solver. Exclusions remain diagnostic, empty
selection emits no pose, and publication rechecks policy freshness/generation.
Policy updates do not reapply configuration or unlock disabled-only mutations.

Spot service version is 0.2.1. The corresponding robot integration uses Java
namespace `frc.robot.vision.generated` and requires advertised tag-policy support.
Legacy binary fixtures are unchanged; separate policy fixtures pin explicit
wire bytes and SHA-256 hashes. Both languages validate the additions.

Health derives from cached Spot observations. Valid zero-tag frames indicate
camera operation without creating pose confidence. A required-camera fault
coexists with continued use of remaining valid cameras. `UseVision` and pit mode
suppress localization capability as before. Fuel detection is unavailable.
RobotManager's request-entry and ongoing scoring/feed health/trust gates and
in-progress-shot policy are retained; only obsolete heading/speed sends were
removed. Turret aiming remains independent of Vision.

## Validation

- Complete Python suite: **429 passed**, including real local NT policy handoff,
  freshness expiry, HTTP integration and unchanged legacy golden bytes.
- Shared JUnit suite: **90 passed**.
- Offseason JUnit suite: **46 passed**, including **30 vision tests** covering
  four synthetic mounts, exact selection sets, camera handoff, unknown alliance,
  loss debounce, old/excluded policy rejection, suppression, disconnect,
  generation/reset invalidation, immutable ownership, cached getters, health
  overrides, correlation, capture history, bounded queue and trust degradation.
- Offseason, competition and new-member Java compilation: passed.
- `spotlessCheck`, changed-Python Ruff checks and both Git diff whitespace checks:
  passed. The documented example matches its compiled offseason test source.

Commands use existing infrastructure:

```sh
# Spot
PYTHONPATH=src:tests .venv/bin/python -m pytest -q
# Robot
./gradlew :shared:test :offseason-bot:test \
  :offseason-bot:compileJava :comp-bot:compileJava :new-member-bot:compileJava spotlessCheck
```

These checks demonstrate software behavior and compilation. They do not establish
physical localization accuracy, actual roboRIO clock qualification or scoring
performance. No scenario runner, new test source set, CI changes or headless
framework changes were introduced. Future full robot fixtures compose scripted
raw `VisionIO` inputs, capture history, explicit clocks and cached status; the
existing runner's manager-idling behavior still requires separate work.

## Remaining commissioning gates

Production camera definitions remain empty. Supply measured NWU translation and
roll/pitch/yaw, verified optical modes and control policies for **left, right,
front, back**, in that stable order. Bind physical devices using Spot's naming
workflow. All four production definitions must be chassis-fixed and required;
synthetic test mounts are never commissioning data.

Qualify four-camera USB/compute throughput, simultaneous visibility/correlation,
partial outages, capture timestamps on the roboRIO, calibration, trust tuning,
accuracy, endurance and recovery. `SpotCameraProfiles.FUSION_ENABLED` defaults
false and heading fusion remains disabled. Existing hardware qualification gates
continue to apply; no Jetson or robot deployment was performed.
