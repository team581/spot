# Spot beta: real-robot integration plan

**Review draft — October 4, 2026**

**Updated October 7, 2026:** explicit startup, boot-time, Ethernet/power recovery and roboRIO–Jetson timestamp-sync requirements added.

**Goal:** deploy Spot on the 2026 offseason robot, with reusable support for every Team 581 2026 robot. Students should configure camera roles and mounts in robot code, assign physical cameras through the GUI, calibrate them, and receive reliable vision measurements through the existing localization system.

This is an implementation specification for review. Proposed thresholds and behavior changes are called out so the team can edit them before handing this plan to an implementation agent.

## 1. Starting point and scope

Reviewed Spot at `61e0c50` and `offseason-2026` at `dd2544af`, including local working files. The Spot checkout's Git remote currently points to `team581/buddy-2026`; resolve naming in documentation without assuming a repository rename is required.

Keep the working Python service and C++/CUDA detector. Reuse capture, scheduling, pose solving, calibration math, frame sharing, replay tools, and regression fixtures. Beta does not need a language rewrite or a new detector.

The October 4 alpha report records 349 passing Python cases, eight passing JavaScript tests, CPU/CUDA image verification, and successful four-camera live operation. These are existing recorded results, not tests rerun for this plan. Real robot timing, measured physical accuracy, sustained operation, and failure recovery still need beta acceptance tests. The older project-status document is stale relative to that report.

Beta includes:

- Any configured camera count within the tested Jetson/USB resource budget; four cameras are the initial acceptance configuration.
- Plug-and-play discovery and capability-based setup, including the team's Swyft camera hardware, currently described as “Swift”/“Generic USB Camera” in alpha notes.
- Persistent camera assignment, calibration, operating settings, and robot configuration cache.
- Production GUI, offline student documentation, and accurate running/deployment information.
- Shared Java integration, chronological pose-estimator ingestion, robot-owned measurement quality, and compact DogLog reporting.
- Consistent automatic startup, minimized measured boot time, and defined Ethernet/power unplug/replug behavior.
- Reliable NT4 timestamp synchronization across startup, reconnects and independent roboRIO/Jetson restarts.
- Shadow rollout, fusion flags, and documented rollback.

Existing Limelight targeting, hub-tag behavior, and ground-camera cluster maps remain usable during migration. AprilTag localization and game-specific targeting are separate capabilities; a generic pose adapter must not pretend to replace cluster-map functionality. Moving camera mounts are supported by the interface and implemented/tested if a beta camera is actually mounted on the turret. Fixed mounts are the initial deployment default.

## 2. Module boundaries

```mermaid
flowchart LR
  U[USB cameras] --> C[Capture and controls]
  C --> D[Detector and pose solver]
  D --> N[NT observations]
  N --> V[Robot validation]
  V --> L[Localization and trust]
  R[Robot camera manifest] --> M[Jetson configuration]
  M --> C
  M --> D
  C --> W[Web GUI and calibration]
  W --> M
```

**Jetson modules**

- `devices`: discover physical devices, group video nodes, expose identity and capabilities, watch disconnect/reconnect.
- `configuration`: validate complete robot manifests, resolve ownership, cache profiles, apply changes transactionally, publish acknowledgements.
- `persistence`: versioned state, camera bindings, calibration generations, operating settings, migrations, backup/export.
- `capture` / `camera_controls`: one capture owner per device, negotiated modes, verified controls, bounded reads and recovery.
- `scheduler` / `native` / `pose`: fair bounded processing, existing detector boundary, calibrated field-to-camera candidates.
- `transport` / `clock`: versioned observations, clock validity, independent health heartbeat.
- `calibration`: shared-frame sessions, background solves, quality reports, atomic save/apply.
- `web`: HTTP API, stream encoding, GUI assets, packaged documentation. No camera opens, pose solving, or direct state-file writes in request handlers.
- `health` / `deployment`: runtime readiness, faults, active build manifest and lifecycle.

These are responsibilities, not a requirement to build a framework or split every function into a package. Move reusable alpha code out of `tools/` into the installed package; retain tools as thin development clients. Headless operation remains available. GUI failure or a disconnected browser must not stop vision.

The installed service must also start with no assigned/enabled cameras, serving discovery, health and Docs. Isolate per-camera initialization errors. Use bounded per-camera result buffering or an equivalent fair output policy so a fast camera cannot evict every result from a slower one. Preview and calibration consumers receive safe shared-frame snapshots and never mutate buffers still owned by detection. Install one compatible OpenCV contrib distribution for ChArUco rather than conflicting standard/contrib wheels; verify CUDA distortion-model compatibility before applying a calibration.

**Robot modules, under `shared/src/main/java/com/team581/vision/`**

- `VisionCamera` / `VisionIO`: queued observations and health from Spot, Limelight, simulation, or recorded fixtures.
- `SpotVisionIO`: NT subscriptions, protobuf decoding, configuration publication and acknowledgements.
- `VisionProcessor`: validation, capture-time mount transform, single-tag candidate selection, uncertainty, rejection reasons.
- `VisionMeasurement`: owned pose/timestamp/deviation data with source identity. Queued measurements must not reference mutable `TagResult` or reused deviation vectors.
- `VisionDiagnostics`: standardized DogLog paths and active faults.

`offseason-bot` provides its robot profile and wires accepted measurements into `Localization`. Other robot projects reuse the shared implementation and supply different profiles. Limelight-specific settings stay inside its adapter.

## 3. Settings as code, with persistent memory

Separate a **logical camera role**, such as `front-left`, from a **physical camera**. `/dev/videoN`, product names, and GUI tile order are not role identities.

| Setting | Authority | Persistence and GUI behavior |
| --- | --- | --- |
| Robot ID/profile, camera roles, required/optional cameras | Robot code | Jetson caches the last accepted complete profile; GUI shows code ownership |
| Mount transform, image orientation, field layout and origin | Robot code | Cached for GUI visualization; robot applies mount transforms for fusion |
| Required capture mode or allowed operating modes; required controls | Robot code | Jetson negotiates only within declared constraints |
| Physical device assigned to a role | Jetson GUI | Stored by robot profile; independent of USB enumeration order |
| Intrinsics, lens model, calibration report/history | Jetson calibration | Bound to physical camera, optical setup and capture geometry |
| Exposure/gain and other allowed tuning | Robot defaults plus explicit policy | Persistent GUI values apply only where robot code allows overrides; pinned code values win |
| Fusion flags, validation thresholds, uncertainty and trust policy | Robot code | Logged and versioned; GUI displays the robot's reported values |
| Layout/overlay preferences | Browser | Local browser storage only |

The student API explicitly distinguishes a default from a pinned value. Do not create an unexplained global “GUI beats code” precedence rule. Show requested, saved and actually applied settings, including control readback and clipping/rejection reasons. Provide **Reset to code defaults** and **Copy settings as code** for allowed tuning. Calibration files and physical selectors do not belong in Java source.

**Manifest handshake:** the robot publishes one complete versioned profile containing `robotId`, a new robot-session ID, role definitions, field layout, and a hash of its content. The Jetson validates it, stages the configuration, commits the accepted snapshot to disk, applies it, and acknowledges the robot hash/session plus its effective runtime generation. Each frame identifies the exact manifest, binding, calibration and runtime generation used. Never acknowledge success before application completes.

The robot accepts runtime generations from coherent acknowledgement metadata for its current profile/session, subject to its calibration/mode requirements; it does not need to predict a GUI-generated calibration hash. Changes to assignments, intrinsics, orientation, mode or field configuration invalidate queued frames from the previous generation.

Fresh code is authoritative even if its content hash matches an older cached profile. Jetson restart can use cached settings for previews and calibration without a robot. Robot fusion requires a fresh session handshake and verified time synchronization. Network loss does not erase settings. A new robot profile must not inherit another robot's role bindings silently; device calibration may be reused only when physical identity and optical mode match.

Store writable state under `/var/lib/spot-vision/`, outside release/source directories. Use schema versions, immutable generation files, an atomically replaced active manifest, last-known-good backup, and directory/file durability appropriate to sudden power loss. Export/import a support bundle. A corrupt cache allows discovery and documentation with a clear fault; it does not create zero mount transforms or provisional production poses. Deployment must preserve this state.

Configuration mutations happen while the robot is disabled, or during an explicit standalone setup session with no robot connected. Losing NT while enabled must not automatically unlock setup: require a confirmed disabled state or an explicit standalone-session transition after the connection is known lost. Reject writes server-side when state is unknown. Recheck eligibility at commit time. Read-only viewing stays available while enabled.

## 4. Plug-and-play cameras and assignment

On connection, enumerate UVC/V4L2 capabilities, capture nodes, USB topology, vendor/product identifiers, serial if available, supported pixel formats/modes and controls. Group metadata/alternate nodes belonging to the same physical camera. Give unassigned devices short persistent display IDs, such as `USB-A3`, and previews through the same device manager used by the runtime.

Assignment workflow:

1. Plug in a camera; its preview appears under **Unassigned**.
2. Click **Assign**. The GUI offers unfilled roles from the current robot manifest, or clearly marked cached roles if the robot is offline.
3. Select the role and preview-confirm it. GUI displays the code-provided mount/orientation and resulting calibration status.
4. Save once; assignment survives application restart and Jetson power cycle.

Use unique physical serial identity when trustworthy. Duplicate/missing serials require persistent USB-port bindings and visible identification by preview. Never match identical cameras by discovery order or assign a new device merely because it is the only unfilled role. A unique-serial device can follow its role across ports; an indistinguishable device moved between port bindings requires reassignment.

A replacement with different observable identity invalidates the prior device calibration. Identical cameras with duplicate serials may be indistinguishable on the same port: software cannot prove a replacement occurred. Provide **Replace camera** to clear the old calibration association, and document that required operator step. Do not claim fully automatic replacement detection without hardware identity support.

**Capability-based operation:** use a generic UVC path first. Any hardware quirks belong in small tested profiles selected by actual identifiers/capabilities, not a hard-coded Arducam/Swyft branch in the service. Menus, units, ranges and read-only/inactive flags come from the device. Optional unsupported controls are unavailable in the GUI; required unsupported controls block production readiness with one clear reason. Verify control writes by readback.

Probe modes with bounded timeouts and verify actual dimensions, format and delivered cadence. Advertised modes are candidates, not proof they work. Alpha notes record that the generic camera's advertised high-resolution modes timed out, while 640×480 worked and its exposure minimum differed from the Arducams.

A new device can automatically choose a working preview mode. Production may automatically select only an allowed mode with matching validated calibration. Never quietly resize a calibrated pipeline or reuse intrinsics after crop, lens/focus, resolution, or relevant sensor-mode changes. Record timestamp quality and actual FPS when the driver supplies less than requested. Excessive USB contention must appear as a system problem, not be hidden by infinite retries.

Health distinguishes **Missing**, **Unassigned**, **Calibration needed**, **Configuration mismatch**, **Ready**, **No tags**, **Recovering** and **Disabled**. Required missing/unready roles fault on the robot; extra unassigned devices produce a setup notice, not a persistent match error. “No tags” is normal operation.

## 5. Observation contract and time

Keep protobuf as the atomic robot-consumption boundary. The robot must not reconstruct a measurement from separately updated pose, valid, tag-count and error topics. Typed pose topics remain useful for visualization, but the alpha's lowest-reprojection-error display choice is not the robot's candidate-selection policy.

Version the beta contract explicitly; use a distinct v2 topic/type during transition. Generate Python and Java from one authoritative schema, with checked-in generation instructions and cross-language fixtures. Package the schema with each release.

Each observation includes:

- Schema, robot/profile session, service session, camera capture epoch, connection/time-sync epoch and frame sequence.
- Logical role and physical binding identity/generation.
- Robot-manifest hash, applied field hash, calibration hash/status and effective runtime generation.
- Field-to-camera pose candidate(s), solve method, used tag IDs and reprojection errors with an explicit definition.
- Camera-to-tag distance and compact observable geometry, such as image tag spread/area, needed by the selected uncertainty policy.
- Timestamp source/quality and processing timing.

Keep IDs, corner/detector diagnostics and existing distortion displacement available for inspection and recorded troubleshooting. Do not automatically make every detector diagnostic a quality gate. Send no-tag frames with empty candidates and progressing sequence. Missing/calibration-invalid cameras can preview and publish diagnostics but cannot supply production-valid candidates. Enforce payload/candidate/tag-count limits.

**Time contract:** the roboRIO is the NT4 server in robot mode; the Jetson is its client. Publish with an explicit timestamp in the Jetson's local NT clock domain and let NT perform client-to-server conversion. Consume the verified server/FPGA-domain capture timestamp in seconds on the roboRIO, then call `Utils.fpgaToCurrentTime()` exactly once at the CTRE boundary. Do not add the NT clock offset twice. WPILib documents these local/server domains and the roboRIO server's FPGA epoch. [WPILib timestamps](https://docs.wpilib.org/en/stable/docs/software/networktables/networktables-intro.html#timestamps)

`ntcore._now()` is local NT time; its availability does not establish synchronization. Gate on actual connection/time-sync validity and invalidate observations across clock jumps and robot reboot. Java `TimestampedRaw` exposes local `timestamp` and `serverTime`; the adapter must handle documented local-value sentinel cases and prove the selected field on the real server, rather than assume two similarly named fields are interchangeable. [TimestampedRaw API](https://github.wpilib.org/allwpilib/docs/release/java/edu/wpi/first/networktables/TimestampedRaw.html)

**Synchronization readiness:** use NT4's built-in time synchronization rather than introduce a second clock-sync protocol. On the Jetson's publishing NT instance, require an actual connection to the expected roboRIO and an available server-time offset for that connection. NTCore's `getServerTimeOffset()` (or the installed RobotPy equivalent) supplies an offset only after client/server synchronization messages have been exchanged; time-sync events report subsequent updates. Track those updates and the connection generation. A valid offset is necessary, but does not by itself prove the required timing accuracy. [NTCore time-sync API](https://github.wpilib.org/allwpilib/docs/release/java/edu/wpi/first/networktables/NetworkTableInstance.html#getServerTimeOffset())

Startup, Ethernet reconnection, either computer's reboot, or an unexpected clock/offset discontinuity returns synchronization to **Waiting**. Discard queued observations from the prior connection/time-sync epoch and require a fresh configuration acknowledgement and newly captured frames after synchronization is re-established. Keep capture, previews and local diagnostics available while robot observations are withheld. Never publish robot-consumable frames using a monotonic fallback clock when NT synchronization is unavailable. Large offsets between unrelated boot epochs are normal; judge unexpected offset changes and timestamp consistency, not absolute offset magnitude.

Expose **Waiting / Synchronized / Invalid**, current offset, last synchronization-update age, sync epoch and discontinuity count in system diagnostics, with compact DogLog state changes. Define sync-update expiry and discontinuity thresholds against the installed NTCore update cadence and measured timing budget; test the chosen values under network load. Verify local NT → server/FPGA → CTRE conversion and capture-time bias separately. Changing Linux wall time or having no internet/NTP must not change fusion time. Resume only when post-reconnect timestamps are fresh, plausible and within the measured clock-error budget; never repair invalid timestamps by clamping them to now.

Current capture timestamps are taken after `capture.read()`, not verified exposure timestamps, and reconnect resets its sequence counter. Beta introduces explicit capture epochs. Prefer verified driver timestamps, preserving their clock and start/end-of-exposure semantics; otherwise characterize read-completion bias and jitter and report that source. A measured per-camera correction is acceptable; a guessed global latency correction is not. Timing uncertainty contributes to motion uncertainty or blocks fusion when excessive.

Publish service/camera heartbeat independently of observation production, at approximately 5 Hz. Report capture, detector and publisher progression separately so a live HTTP process cannot make a frozen pipeline look healthy. Health/status traffic uses modest rates; observation traffic is explicitly queued/bounded with `sendAll` and suitable subscriber capacity. An acknowledgement of robot consumption is telemetry, not processing backpressure.

## 6. Robot validation, fusion and trust

Keep the student integration small: one camera configuration table, one shared vision object, and one localization ingestion call. Intended API shape, with names finalized during implementation:

```java
var vision = SpotVision.create(RobotVisionConfig.OFFSEASON);
// In the normal robot/localization loop:
vision.drainMeasurements(localization::addVisionMeasurement);
```

Each camera configuration declares a name, a WPILib `Transform3d`, required/optional status, operating policy and optional device hints. No per-camera heartbeat timers, NT topic strings, protobuf handling or repeated fallback code in student configuration. Provide a complete compiling example, not only this sketch. Use WPILib +X forward, +Y left, +Z up and explicit angle units; do not carry a `right` field into WPILib transforms without conversion.

**Measurement processing:**

1. Decode bounded packets; require supported schema, known role, current session/configuration, validated calibration and correct field origin/hash.
2. Require fresh, synchronized capture time within explicit history bounds. Reject unreasonable future timestamps instead of clamping them to now.
3. Deduplicate by service session/capture epoch/sequence. Clear appropriate state on reconnect/reset; never replay an old retained sample as new.
4. Validate finite positions, normalized valid rotations, plausible geometry, positive-depth solver results, known tags and acceptable residuals.
5. Apply the role's robot-to-camera transform at capture time. Fixed mounts use the code transform; moving mounts use timestamped joint history. Missing history is a rejection, not substitution of the current angle.
6. Check robot field bounds and physically reasonable Z/roll/pitch, accounting for the robot's actual terrain and tilt. Avoid a blanket flat-floor assumption on a robot that traverses bumps.
7. Resolve single-tag IPPE alternatives only when capture-time heading/geometry distinguishes them by a documented margin. Reject undecidable candidates. Disabling heading fusion does not make an ambiguous translation safe.
8. Compute conservative standard deviations and evaluate capture-time innovation against pre-update estimator state. Separate normal tracking from explicit initialization/relocalization.
9. Deliver accepted observations in capture-time order and update diagnostic/trust inputs with the same accepted observations and pre-fusion comparisons.

Collect and sort across all cameras and across loop boundaries using a small bounded reorder window. Release by a time watermark/deadline, without waiting for an offline camera; reject and count observations older than the last fused watermark. Initial window: 20 ms, subject to measured delivery jitter. Do not confuse per-camera transport order with globally ordered fusion. Bound memory and per-loop work; count loss when overloaded. Clear queues/history eligibility around pose resets so pre-reset frames cannot pull the robot back.

CTRE accepts per-measurement X/Y standard deviations in metres and heading in radians, and requires its own time epoch. Its documentation confirms the existing FPGA conversion boundary. [CTRE vision API](https://api.ctr-electronics.com/phoenix6/stable/java/com/ctre/phoenix6/swerve/SwerveDrivetrain.html#addVisionMeasurement(edu.wpi.first.math.geometry.Pose2d,double,edu.wpi.first.math.Matrix))

**Uncertainty policy:** begin with translation-only fusion and retain gyro heading. A valid multi-tag solution does not automatically justify trusting its yaw. Enable independent vision heading only after ground-truth evidence and separate team review. Single-tag acceptance still requires decisive candidate selection.

Implement a robot-owned tunable model with positive floors, camera-specific coefficients, range, geometric conditioning, residuals and measured motion/timestamp uncertainty. Validate the model against held-out measured robot trials. A simple range-squared baseline with conservative tag-count benefit is sufficient initially; near-identical views and extra corners do not create independent measurements. Cap any tag-count improvement and account conservatively for simultaneous cameras viewing the same tags. Document the approximation because CTRE's three-axis deviations do not represent full cross-camera covariance.

Do not copy Limelight ambiguity numbers or rejection thresholds. Retaining two physically valid IPPE solutions is objectively useful; an invented Limelight-compatible scalar is not required. Raw-to-undistorted pixel displacement measures lens correction, not residual lens error. Keep it diagnostic unless field data supports an uncertainty penalty. The current Spot `distance² / tagCount²` formula is an experimental reference, not established confidence math. Prevent zero deviations and verify the CTRE-compatible way to suppress heading updates rather than assume infinity behaves safely.

**TrustFactor review:** preserve the public `get/isLost/isTrustworthy` API used by robot behavior, but treat its value as a heuristic, not a probability or estimator covariance. Proposed revision: update from each accepted measurement's pre-fusion capture-time innovation and its uncertainty; group correlated evidence so additional cameras do not automatically make the score better; track last accepted evidence and degradation from actual odometry travel, elapsed time and collision events. Pose-estimator corrections must not be counted as physical travel. Log evidence age separately. Rejections never improve trust. Reset explicitly establishes a new history baseline. Fit/review thresholds before enabling the revised score in aiming/readiness decisions.

## 7. Fallback ownership

| Failure | Jetson owns | Robot owns |
| --- | --- | --- |
| Camera disconnect, read timeout or bad frames | Per-device bounded retries/backoff; restore binding and verified settings; new capture epoch | Stop using stale observations from that role; continue remaining sources |
| Unsupported controls/mode or bad calibration | Report exact setup problem; preview/diagnostics where possible; no production-valid pose | Require current matching metadata; reject that role's measurements |
| CUDA recoverable failure | Validated, explicit CPU fallback when configured; report backend and degraded capacity | Accept only fresh quality-valid results; no second detector fallback |
| Native fatal error or dead worker | Watchdog/systemd recovery with restart limits; readiness requires worker progress | Mark Spot unavailable and continue healthy sources/odometry |
| CPU fallback overload or thermal throttling | Bounded queues and configured processing-rate reduction; preserve camera fairness | Reject excessive-age measurements; log degraded availability |
| NT disconnect/time-sync loss | Continue capture/setup, cache settings; reconnect; no backlog replay | Suspend Spot fusion until fresh synchronized handshake and frames |
| Ambiguous/physically implausible pose | Publish valid solver alternatives/diagnostics | Select or reject once, using timestamped robot context |
| GUI/stream failure | Isolate preview work and reconnect browser; keep vision running | No control-loop dependency on GUI |
| All vision unavailable | Report health | Continue odometry/gyro; degrade trust and dependent readiness normally |

A single missing camera or recoverable exception must not take down others, including failures during startup. Guard known native-invalid settings before calling C++; retain the alpha decimation protection. For an unrecoverable shared native crash, one supervised service restart is the baseline; do not add robot-driven restart loops. The watchdog must detect dead capture/detector/output workers, not merely ping from a live main thread.

Recoverable detector failures use one explicit state transition into CPU mode, with bounded GPU retry/recovery and a recorded backend generation; do not reconstruct a detector and emit a fault on every frame. Thermal/overload rate reduction may change processing cadence, but optical mode changes still require matching calibration and a new runtime generation.

Other healthy cameras and existing Limelights remain independent sources. Do not automatically turn every Spot rejection into a paired Limelight measurement or fuse the same exposure twice. If a paired primary/backup policy is later needed, define it once at robot source selection with recovery hysteresis. No stale-pose reuse, fake origin pose, or automatic estimator reset when vision disappears.

### 7.1 Consistent startup and minimized boot time

Power-on, application restart and recovery use the same installed service and readiness rules, without SSH, a browser, manual launch or internet access. Start correctly whether the Jetson or roboRIO comes first, whether Ethernet is absent, and whether cameras enumerate late. Do not block local capture, discovery, health or Docs on network-online waits, a reachable roboRIO, visible tags, or every configured camera being present. Resolve network connectivity asynchronously. Maintain one service instance and one capture owner per physical camera.

```mermaid
flowchart LR
  B[Boot or restart] --> S[Load release and saved state]
  S --> C[Discover and start cameras]
  S --> N[Connect to roboRIO]
  C --> G[Per-camera readiness]
  N --> T[Sync and config handshake]
  G --> R[Robot acceptance gates]
  T --> R
```

Use explicit startup stages and per-camera readiness. A camera is ready when its identity/binding, mode, controls, calibration and processing progression are verified; tag visibility is not required. Robot fusion additionally requires the current profile/session and synchronized timestamps. Missing optional cameras do not delay healthy ones. Missing required cameras report degraded system readiness while healthy roles remain available under the existing fusion policy. Repeated startup with unchanged hardware/configuration must produce the same bindings, applied settings and readiness decisions.

Minimize the critical path: install/build dependencies and native modules during deployment, keep model/layout/calibration assets local, overlap independent initialization where safe, and avoid fixed sleeps, unnecessary device reprobes, repeated control writes or heavyweight preview work before processing starts. Use bounded readiness checks and retry backoff. Do not weaken calibration/configuration/sync gates to meet a boot target.

Measure OS boot, service start, state load, camera enumeration, first processed frame, NT connection, synchronization, configuration acknowledgement and robot-side vision availability using monotonic durations. Report the bottleneck, p50/p95 and worst case for cold boots and warm service restarts separately. No-tag operation counts as vision availability once valid empty observations progress; first accepted pose depends on tag visibility and is a separate metric. Initial targets and repeated-cycle tests are in Section 13.

### 7.2 Defined Ethernet and power unplug/replug behavior

| Event | Required behavior while unavailable | Required behavior after restoration |
| --- | --- | --- |
| Ethernet unplugged; Jetson remains powered | Keep camera processing/previews and saved settings; mark robot link/sync unavailable, withhold robot observations, and discard unsent measurement backlog. Robot expires Spot measurements and continues other vision/odometry | Reconnect automatically without service restart; establish a new connection/time-sync epoch, refresh the profile handshake even if the robot session is unchanged, and deliver only fresh post-sync frames |
| Jetson power removed | Robot detects stalled Spot health and expires measurements; odometry/gyro and other sources continue. Incomplete settings/calibration writes cannot become the active committed generation | Jetson boots automatically into the installed release, restores the last complete committed state, creates a new service session, verifies devices/settings and syncs before robot use |
| roboRIO power removed or robot program restarted while Jetson stays on | Jetson keeps local operation but suspends robot observations and invalidates the previous robot connection/sync state | Accept the new robot session and FPGA epoch, reapply/acknowledge its current profile, clear old measurement queues and use newly synchronized frames |
| Both computers lose power, or Ethernet and power return in any order | Saved settings remain intact; no assumption about which device starts first | Each component retries its own dependency asynchronously and converges to the same ready/degraded state; no manual ordering or estimator reset is required |
| Camera/USB-hub power interrupted independently | Existing per-device recovery applies; unaffected cameras continue, and frames from the old capture epoch become ineligible | Rediscover the same persistent bindings, verify mode/control/calibration compatibility, create new capture epochs and recover only verified roles |

Short cable interruptions, extended outages and repeated flapping follow these same rules. Recovery may run while the robot is enabled using its already authorized profile; this does not unlock GUI configuration changes. Uncommitted drafts may be lost after power removal, but the last committed settings must survive. The plan guarantees application-state recovery on a healthy filesystem; test sudden-power-loss boot reliability and report hardware/filesystem failures explicitly. Reconnect events never silently reseed the estimator or clear accumulated trust degradation. Active faults clear only after verified pipeline/connection recovery.

## 8. Production GUI

Persistent left sidebar:

- **Overview**
- **Cameras**, with one entry per configured role and an **Unassigned** entry when needed
- **Calibration**
- **Network & System**
- **Docs**

Use Team 581/Blazing Bulldogs identity, approved logo assets and flat team-color accents over neutral surfaces. If exact brand assets are unavailable, use a simple `581 / Spot` wordmark and isolated theme tokens for later replacement. No gradients, glow, decorative animation, marketing text or tutorial paragraphs. Use short labels, units and meaningful status text; deeper instructions live in Docs. Status must be readable without relying on color. Support keyboard interaction, laptop screens and a collapsed sidebar on smaller screens.

**Overview:** all role previews, including missing-camera placeholders; name, capture/detection FPS, tag count, calibration/readiness and latest measurement age. A compact system strip shows robot/NT connection, clock validity, ready/required count and active release. Clicking a tile opens that camera. Hide stale overlays; label frozen/stale frames visibly. Detailed counters live on deeper pages.

**Camera page:** large stream; toggle tag/corner/axis overlays; freeze inspection; observed and used IDs; solver alternatives; reprojection metrics; field/camera/robot visualization with correctly named coordinate frames. Display robot-reported acceptance/rejection and selected candidate separately from Jetson solver/display output; if no robot is connected, show that state. Add physical identity/binding, requested/applied mode, calibration history and code-owned mount view. Expose supported exposure/gain first, advanced controls in an expandable section. Draft edits have Apply/Reset; live preview tuning must never masquerade as saved state.

**Calibration:** select one, several or all configured cameras in one session; use live tiles, board detection, coverage grid, view count, quality and progress. Operators can move one board between camera views; simultaneous visibility is not required. Start/pause/retry per camera or all. Background compute must leave UI and other cameras responsive. Show concise actionable failure reasons and reviewable metrics.

**Network & System:** configured/discovered robot endpoint, link and NT status, clock state, USB topology, CPU/GPU/thermal state, drop counters and active faults. Include startup stage/timings, time-sync status/update age, reconnect history, deployment/build information and support-bundle export. Beta's networking page is primarily diagnostics; changing OS addresses from the GUI is out of scope unless added explicitly. Keep the static Jetson setup procedure and expected power/Ethernet recovery behavior in Docs.

**Docs:** packaged locally, searchable and reachable from every page, with contextual deep links. Cover new/replacement cameras, role assignment, duplicate serials, ChArUco setup, calibration quality, measuring mounts/coordinate axes, GUI controls, Java integration, quality/fault meanings, logs, networking, deployment and rollback. Provide a student quick start and one complete offseason robot example. No internet dependency or second manually maintained copy of the same guide. Package documentation and GUI assets in installation tests.

API mutations use validated structured requests, a session/CSRF control, same-origin checks and optimistic revision checking; two browsers must not silently overwrite each other. Bound stream resolution/rate/client count and stop hidden-tab work. Local network operation needs no cloud service. Do not expose an unauthenticated shell or arbitrary filesystem paths through the GUI.

## 9. Calibration save and apply

Reuse the team board defaults: 15×15 squares, 30 mm squares, 22 mm markers, `DICT_4X4_250`. Board configuration and distortion model remain explicit and persisted. Verify the real printed dimensions and image sharpness; a green coverage grid alone is not a passing calibration.

Keep automatic view diversity/duplicate rejection and outlier handling. Add an explicit separate validation capture set not used to fit intrinsics, plus physical pose checks in robot acceptance. Calibration is intrinsic/lens calibration; it does not determine robot mount position. Multi-camera capture does not require rigid inter-camera calibration for independently solved AprilTag poses.

Store physical device identity, optical-mode signature, board/model, fit and validation metrics, date, algorithm/build and content hash. Calibration compatibility depends on optical geometry, not just a logical name. Recalibrate after lens/focus/crop changes or an incompatible replacement; preserve earlier known-good generations.

**Save/apply is a transaction:** validate all selected results, write a complete staged generation, atomically activate its manifest, rebuild affected detector/solver state at a safe boundary, discard old-generation queued frames, and publish the applied generation. The GUI says **Applied** only after acknowledgement. If any selected camera fails, none of that selected group is activated; the operator may explicitly choose a smaller passing group. Solve, save, load and power-loss failures leave the previous complete active generation usable. Permit rollback while disabled.

The existing alpha implementation writes calibration files sequentially and its GUI saves one camera at a time. Individual atomic file replacement is not a group transaction. Its documentation also describes holdout validation that needs an explicit implementation/test in beta. Address these gaps rather than assume the documented behavior already exists.

## 10. Showing the last Jetson update

Every release has an immutable build manifest: source commit, source-tree/dirty-content fingerprint where applicable, application version, protobuf version, native detector build/hash and build time. Deployment records target, release ID, deployment time and verification outcome separately from compilation.

Startup loads the manifest from the actual installed release. Report running release/native build, deployment timestamp, process start time and rollback state through HTTP and NT; DogLog records them once/on change. Verify the native module loaded by the process, not just the checkout revision. A checkout can change without changing an installed package or running process.

Sidebar footer: **Updated Oct 4, 18:42 · abc1234**. System page distinguishes **Last successful deployment**, **Running release** and **Started**. Rollback displays the restored active release and the latest deployment attempt separately. If wall time is unreliable, show **Time unavailable** with release identity and monotonic uptime; do not fabricate a calendar time. Deploy readiness must allow realistic camera initialization time before declaring failure, reflecting the alpha's initial premature readiness rollback.

Update systemd for least-privilege writes to `/var/lib/spot-vision` while retaining read-only application/config assets. Test the real installed service and writable-state paths; the current unit makes `/etc/spot-vision` read-only. Provide a release activation/rollback procedure that preserves assignments/calibration and verifies installed Python/native artifacts, GUI, NT and required camera readiness.

## 11. Existing behavior requiring team review

These are specific code findings, not assumptions that Limelight behavior is inherently wrong. Preserve existing robot behavior behind flags until the edited plan authorizes changes to shared behavior.

| Finding | Risk / proposed treatment |
| --- | --- |
| `shared/.../localization/TrustFactor.java` weights by `std / totalStd`; the comment describes a different formula | Noisier observations get more weight. Fix the arithmetic under a reviewed model; inverse variance is appropriate only for independent, time-aligned data |
| Trust averages asynchronous camera poses and compares them with one average-timestamp pose | Motion and different latencies contaminate disagreement. Evaluate evidence at each capture time; do not average unaligned positions |
| Localization calls trust after estimator updates; travel uses changes in fused pose | Circular comparison can look artificially good; vision corrections can look like travel. Use pre-fusion residuals and actual odometry increments |
| Empty localization result lists still compute `0 / 0`, then sample pose at NaN | Add an early empty-list return; test no-vision operation |
| `Localization.getPose(timestamp)` substitutes current pose when history is unavailable | Unsafe for candidate selection and innovation. Use an explicit optional/history-availability boundary for vision |
| Fixed shooter/left/right ingestion order and one mutable result per camera | Intermediate frames are lost and ingestion is not chronological. Drain owned queued measurements |
| Global `StaticLatencyAdjustment` plus clamping timestamps to now | Can conceal clock mistakes. Spot uses measured capture timing and explicit rejection; audit any continued Limelight correction separately |
| Limelight validator rejects X=Y=0 and uses fixed ambiguity/angular-rate thresholds | Origin is a legitimate coordinate; explicit validity replaces sentinels. Retune rate/quality policy from Spot data instead of copying constants |
| Limelight MT1 is required before MT2; close-range path can combine MT2 translation/time with MT1 heading | Source/frame consistency and heading independence deserve review. Keep this policy inside the Limelight adapter; do not reproduce it for Spot |
| Existing camera config says `right`, but `getTransform3d()` uses that value directly as WPILib Y | Verify physical signs and handedness with measured fixtures before importing mounts |
| Offseason `Hardware.java` instantiates four OFF cameras named `placeholder` with zero mounts | These are not usable fallbacks or mount references. Use actual CAD/measurements and hardware inventory |
| Old Spot spec prescribes a native-daemon rewrite, extensive default logging and `tagCount²` confidence scaling | This beta plan supersedes those conflicting prescriptions; retain working modules and justify confidence experimentally |
| Alpha typed pose picks minimum image error for display; provisional calibration can still produce poses | Robot consumes candidate packets; production rejects provisional calibration |
| Alpha four-camera rates vary, result queues drop frames, and some short NT checks intermittently fail | Investigate output/preview bottlenecks and timestamp delivery; a retry passing is not production qualification |

**Review decisions to edit before enabling robot fusion:** approve the trust-policy revision; translation-only initial mode and later heading gate; fixed-camera scope versus actual turret installation; field-layout variant for the real test field; required camera roles/mounts/modes; correlated-camera policy; and the numerical beta targets below. Infrastructure implementation can proceed independently of tuning decisions, but fusion/readiness changes remain behind flags.

## 12. DogLog and faults

Centralize diagnostics in the shared adapter/processor. Use the installed DogLog API/version; do not upgrade dependencies solely to implement this plan. Existing code already supports `log`, `logFault` and `clearFault`; DogLog supports WPILOG and NT reporting. [DogLog usage](https://doglog.dev/getting-started/usage)

Default data:

- Startup/on change: running release, native build, robot profile/manifest, field, binding/calibration revisions and policy flags; startup-stage durations and connection/time-sync transitions.
- Every processed accepted measurement: source/session/frame identity, capture time, measured pose, used IDs, chosen deviations, pre-fusion residual and acceptance reason. Rejected-frame reasons use stable enums and counters; detailed rejected candidate records belong in debug capture.
- At 2–5 Hz: per-role health, last-frame/evidence age, capture/detection/accepted rates, latency and drop/rejection counters; system clock/backend/thermal summary.
- Trust: score, freshness, last accepted evidence, lost/trustworthy state and collision/reset events. Reuse existing estimated-pose logging.
- Fault transitions: required camera missing/unassigned/uncalibrated, config mismatch, stale pipeline, clock invalid, degraded detector and persistent overload. Clear automatically on verified recovery.

One owner raises each active fault; avoid duplicate Jetson and robot warning text for the same root problem. Jetson technical detail stays in its bounded structured logs/support bundle; robot DogLog records the actionable condition. No default corner arrays, image bytes, per-frame UVC controls, giant protobuf dumps or repeated stack traces. Provide a time-limited debug recording/export mode for detailed investigations.

## 13. Implementation order and acceptance

Implement in reviewable stages, each with targeted tests and a working installed artifact.

| Stage | Deliverable | Exit gate |
| --- | --- | --- |
| 1. Contract and fixtures | Profile ownership/schema, v2 protobuf, clock/session policy, Java API and golden packets | Python/Java agree on candidates, transforms, IDs, hashes and timestamps; numerical/frame semantics documented |
| 2. Device and persistent state | Discovery, role assignment, capability profiles, cached manifest, transactional generations and automatic startup | Swyft + Arducam startup/reconnect/reboot, duplicate identity and missing-role tests; measured cold/warm startup; no selector edits required for ordinary setup |
| 3. Production web/calibration | Installed sidebar GUI/API/docs and shared-frame multi-camera calibration | GUI usable offline; concurrent-client conflicts handled; group apply/rollback and calibrated mode checks pass |
| 4. Shared robot integration | Spot IO/processor, Limelight adapter, owned queue, CTRE boundary and DogLog | Offseason tests plus all affected robot projects compile; malformed, stale, ambiguous, reset and reorder fixtures pass |
| 5. Robot shadow runs | Spot connected to real roboRIO; fusion disabled; robot-reported decisions visible in GUI | Ground-truth accuracy, timestamp conversion/sync recovery, load/thermal and Ethernet/power-cycle evidence meets targets |
| 6. Controlled fusion | One fixed camera, then multiple; reviewed trust policy and flags | Driving/no-tag/fault recovery tests pass; readiness behavior reviewed; rollback exercised |
| 7. Student handoff | Final documentation, support/deploy tools and second robot profile example | A student configures/assigns/calibrates a replacement camera and explains its robot integration without source spelunking |

**Proposed initial targets — engineering goals, not claims established by alpha:**

- Cold power-on to robot-side vision availability p95 ≤60 s with healthy preconnected cameras and an already available roboRIO; service restart to availability p95 ≤10 s. Local health/GUI responds within 5 s of service start even with no Ethernet or cameras. Test at least ten cold boots and ten warm restarts, recording worst case as well as p95. If the roboRIO/link arrives later, report dependency wait separately and enforce the reconnect target below. Establish a measured baseline first, then reduce the dominant delays; the team may edit these initial budgets after reviewing target-hardware results.
- Four enabled cameras each sustain at least 15 usable detections/solves per second when appropriate tags are visible, at approved camera modes; normal GUI viewing reduces each camera's throughput by no more than 10% versus its headless baseline. Calibrating may reduce throughput and is disabled-only; document that load separately.
- Capture-to-robot-consumption latency p95 ≤100 ms; production rejects frames older than 250 ms or outside verified estimator history. Future tolerance starts at 5 ms; apparent future times beyond it are rejected. Prove clock error ≤5 ms independently of the software's own reported offset.
- At fixed surveyed poses over the declared 1–5 m operating range: median planar error ≤0.10 m and p95 ≤0.20 m. Dynamic planar error p95 ≤0.25 m on surveyed repeatable paths. Evaluate each camera and combined estimator, tag geometries, tilt, lighting and robot speeds separately. Heading remains unfused until a separate accuracy target is reviewed.
- Detect a stalled required camera pipeline within 0.5 s; stale frames cease fusion at the age gate. Reconnect begins immediately with bounded backoff; under known-good hardware/settings, restore readiness within 5 s after device enumeration or NT reconnection/time sync.
- Thirty-minute four-camera thermal run with representative streams and motion: no uncontrolled memory/queue growth, no sustained starvation, no fatal failures and no timestamp discontinuities. Result/transport queue loss <1% under nominal load; intentional latest-frame overwrites are counted separately.
- Jetson/roboRIO independent reboot, USB unplug/replug, physical Ethernet unplug/replug, abrupt power loss/restoration, corrupt state, invalid calibration, profile mismatch, forced CPU fallback, unsupported modes, dead output worker and rollback all fail safely and recover as specified. No estimator reset, old-frame replay, fake origin or duplicate fusion. Test Ethernet outages of approximately 1 s, 30 s and 5 min; repeated link flapping; Jetson-first/roboRIO-first startup; Ethernet absent at boot; camera/hub power loss; and power removal during settings/calibration commit. Use a disabled robot for physical power-cycle qualification.
- Timestamp qualification covers initial startup, each reconnect/reboot ordering, CPU/GPU/network load and altered wall time. Verify synchronization is unavailable before the current connection's NT exchange, old-epoch frames cannot be accepted, and post-recovery error remains within the existing ≤5 ms clock budget. Record raw local/server/FPGA/CTRE timestamps and synchronization transitions in the qualification report; an NT connection or available offset alone is not a passing timing test.

These thresholds live in code/configuration with units and documented reasons. If hardware misses them, produce a measured bottleneck report and propose revised modes/budgets for team review. Do not silently lower gates or certify a 1 FPS liveness check as performance acceptance.

Tests must include cross-language serialized fixtures; known-transform geometry; independent clock tests on the actual roboRIO; deterministic startup state transitions; missing/delayed network and cameras; time-sync loss/expiry/discontinuity; Ethernet reconnect and independent power-cycle epochs; both IPPE alternatives; out-of-order arrivals across robot loops; packet bounds/unknown schemas; device reconnect epochs; reset histories; correlated observations; empty measurement lists; cache/session behavior; settings/calibration group power-loss recovery; web mutation eligibility; packaged assets; slow browsers; preview load; and installed artifact identity. Keep CUDA tests strict when certifying CUDA, so CPU fallback cannot hide a GPU failure.

Update `README.md`, the project-status document and the original design contract to point to this reviewed beta specification and remove contradictory operational claims. Keep the alpha test report as historical evidence.

## 14. Implementation-agent handoff

Use the team-edited version of this plan as the beta contract. Work in `spot-2026` and `offseason-2026`; put reusable robot code in `shared`, with offseason-specific wiring/configuration in `offseason-bot`. Preserve unrelated working changes. Do not copy competition mounts onto the offseason robot or replace OFF placeholder Limelights with invented hardware settings.

Start with protocol/configuration and acceptance fixtures, then device persistence, installed GUI/calibration, and shared robot integration. Preserve the tested alpha detector/pose pipeline and historical evidence. Maintain explicit review items and feature flags for trust/heading changes. Do not broaden this work into shooter, path-planning, drivetrain or ground-object rewrites.

For each stage, deliver changes in both relevant repositories, tests/results, schema/API docs, remaining hardware checks and rollback instructions. Software-only work may be complete before robot qualification; label unperformed hardware gates clearly. Do not mark beta robot-ready until the real offseason bot passes the required measurements and recovery tests.

Jetson validation uses the repository's dedicated SSH key and deployment procedure. Hardware deployment/fusion activation happens during the authorized implementation session with a disabled robot and measured mounts. This planning task performs no deployment or robot changes.

**Beta is complete when:** students can plug in supported cameras, assign code-defined roles, calibrate multiple cameras, inspect streams/health, identify the running update, and obtain correctly timed, quality-controlled measurements in the offseason robot's estimator and reviewed trust system—with reusable configuration for the other 2026 robots.

### Review references

- Robot source: [team581/offseason-2026](https://github.com/team581/offseason-2026). Key reviewed paths: `offseason-bot/src/main/java/frc/robot/{Hardware.java,vision/,localization/Localization.java}`, `shared/src/main/java/com/team581/{localization/TrustFactor.java,config/CameraConfig.java,vision/}`.
- Current Spot remote: [team581/buddy-2026](https://github.com/team581/buddy-2026). Key reviewed paths: `src/spot_vision/`, `proto/vision.proto`, `tools/{prototype_daemon.py,prototype_stream.py,alpha_calibration.py}`, `deploy/`, and `docs/Alpha Verification.md`.
- The existing specifications, calibration plan and project-status document provide historical intent; observed implementation and the October 4 verification report take precedence when those documents disagree.
