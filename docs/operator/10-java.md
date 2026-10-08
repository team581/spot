Title: API / Java integration
Group: Reference

# API and Java integration

## Shared implementation

The offseason checkout uses `shared/.../vision` for SpotVisionIO, VisionProcessor, CaptureHistory, MeasurementQueue, VisionPipeline, diagnostics and reviewed trust. Robot-specific measured mounts, required names, allowed modes, controls and flags live in SpotCameraProfiles. The actual offseason profile deliberately contains no invented Spot mounts. Limelight policy stays in its adapter, and all released immutable measurements share chronological ordering.

The compiling example below accepts measured mounts and verified modes as arguments. Use the robot's real blue-wall-right field layout and NWU transforms. `poseAt` must return empty outside available FPGA-time history; CTRE callers convert FPGA to CTRE time exactly once at history lookup and ingestion.

```java-example
```

## Timestamp and observation contract

Production topics use `/Spot/v2` with `proto:spot.vision.v2.*` raw packets. The schema is installed under `spot_vision/schemas` and checked in as `proto/vision_v2.proto`. Coherent observations carry session, generation, binding, calibration, mode, sequence and capture epoch. The NT sample timestamp is robot-facing FPGA time after built-in translation; the internal Jetson local-NT timestamp is diagnostic and is never treated as an FPGA timestamp.

The receiver rejects stale, future, conflicting-domain, pre-reset, duplicate, old-epoch or mismatched packets. Bounds are 64 KiB per observation, 32 cameras, 64 tags and two candidates. Timestamp sentinels 0/1 are handled only on a verified NT server; actual roboRIO timing remains a hardware qualification gate. Max age starts at 250 ms, future tolerance 5 ms and reorder watermark 20 ms; no timestamp clamping is allowed.

## HTTP boundary

Get `/api/session` to establish the HttpOnly SameSite browser cookie and CSRF token. Mutations POST JSON to `/api/operations` with matching Origin, X-Spot-CSRF, `operation`, `payload`, and a unique bounded `request_id`. The response is a job ID; poll `/api/jobs/ID` for applied/rejected acknowledgement. Handlers enqueue work and never open cameras, solve calibration or write state.

Ordinary bodies are bounded to 64 KiB, imports to 2 MiB, sessions to eight, HTTP workers to sixteen and live mutations to five per second with a burst of two. Revisions prevent concurrent overwrite. Theme is browser storage and never goes through this API.

A measured `qualify-timing` payload contains revision and record: identity, System timing signature, timestamp_source `read-completion-local-nt`, nonpositive correction_us, positive uncertainty_s at most 0.02, measured_cycles at least 100, and explicit evidence/conditions. Synthetic unit-test timing records are not qualification evidence.
