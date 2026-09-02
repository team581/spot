# Buddy Vision Project Status

Last updated: September 1, 2026

Overall status: **Raw CUDA AprilTag detection is working on the target Jetson and camera. Calibration, pose accuracy, NT4 transport, deployment reliability, and robot integration remain to be validated.**

The complete design requirements are in [Vision Solution (Buddy) Specs.md](./Vision%20Solution%20(Buddy)%20Specs.md). The current implementation intentionally overrides the original native-daemon recommendation: service orchestration is written in Python, while Team 766's detector remains in C++20/CUDA behind a pybind11 extension.

## Executive Summary

The first-pass Buddy vision service has been implemented. It includes the imported Team 766 CUDA AprilTag detector, a Python camera and scheduling service, pose-solving code, protobuf and NT4 support, health reporting, replay and benchmark commands, and systemd deployment assets.

The first hardware checkpoint has passed. On `orin-1`, the service captured frames from the attached Arducam OV2311 and repeatedly detected a visible 36h11 tag. One observed result reported tag ID 8, hamming distance 0, decision margin approximately 105.45, no frame overwritten before processing, and approximately 6.43 ms total processing time. Corners were also returned correctly.

This proves the camera-to-CUDA raw-detection path. It does not yet prove field-relative robot pose accuracy or production reliability.

## Current Target Configuration

| Item | Current state |
| --- | --- |
| Compute | NVIDIA Jetson Orin Nano 8 GB, device name `orin-1` |
| Jetson software | L4T R36.4.3, CUDA 12.6 |
| Python | 3.10.12 |
| OpenCV | 4.8.0 with GStreamer support |
| Camera | Arducam OV2311 USB camera, model UC621 |
| Camera selector | Stable `/dev/v4l/by-id` selector configured |
| Configured mode | MJPEG, 1280×720 at 50 FPS |
| Exposure | Manual, 1000 µs |
| Gain | 20 |
| Tag family | 36h11 |
| Calibration | Not yet configured |
| NT4 | Present in the implementation but currently disabled in the local configuration |

The camera mode and exposure values are working first-pass values, not final production tuning.

## Implemented

### Native detector

- Team 766's CUDA detector core is imported and pinned with provenance in `cpp/team766/UPSTREAM.md`.
- The imported code includes thresholding, connected components, point collection, quad fitting, and AprilTag decoding rather than only the top-level CUDA file.
- A pybind11 module exposes CUDA and pinned CPU detectors to Python.
- NumPy input validation covers type, shape, dimensions, continuity, and row stride.
- Python retains the input frame during detection and releases the GIL while native detection runs.
- The Python-to-C++ boundary does not clone the image. The required host-to-device CUDA transfer remains.
- Detection results include IDs, canonical corners, hamming distance, decision margin, and timing information.

### Python service

- Headless camera probing and format/control reporting.
- Explicit GStreamer/OpenCV capture pipelines.
- One capture thread and latest-frame slot per camera.
- Fair round-robin detection scheduling.
- Bounded result queues and overwrite/drop accounting.
- CPU comparison and fallback support.
- Single- and multi-tag pose-solving paths using OpenCV PnP routines.
- Calibration and WPILib field-layout loading and validation.
- Protobuf message generation and Python NTCore publication support.
- Health state, structured logging, temperature reporting, reconnect behavior, and revision reporting.
- Live probe, daemon, replay, CUDA/CPU comparison, benchmark, and calibration-validation CLI modes.
- systemd service and installation assets.

### Build and deployment support

- CMake, pybind11, and scikit-build-core packaging.
- Jetson-specific CUDA build adjustments.
- NVIDIA CCCL is fetched at its pinned revision by CMake. An explicitly supplied `BUDDY_CCCL_ROOT` remains available for offline builds.
- Local CCCL checkouts and Python wheelhouses are treated as regenerable build caches and excluded from source control.
- Deployment uses the checked-in, credential-free `deploy/install.sh`; the temporary credential-bearing deployment helper has been removed.

## Validated So Far

- The initial host-side test suite passed 17 tests when the implementation was completed.
- The non-CUDA package build and CLI paths were exercised on the development machine.
- Local protobuf and NT-related tests passed during the initial implementation.
- The target Jetson can load and run the CUDA detector.
- The Arducam capture pipeline supplies frames in a form accepted by the detector.
- A known 36h11 tag is detected with the expected ID, zero hamming errors, strong decision margin, and valid corners.
- The observed live result showed no pending-frame overwrite before processing.
- The service operates headlessly without requiring an OpenCV window or browser.

The raw live tag-detection milestone is therefore complete.

## Incomplete or Not Yet Validated

- The OV2311 has not been intrinsically calibrated for the exact resolution, format, focus, and mounting configuration.
- The camera-to-robot transform has not been measured and validated.
- Field-layout revision loading and known-field-tag pose accuracy have not been checked on the Jetson.
- Single-tag IPPE dual candidates and multi-tag SQPnP/refinement have not been validated with physical targets.
- End-to-end NT4 delivery, timestamps, duplicate frames, empty frames, and revision topics have not been checked against a robot-like subscriber.
- The systemd service has not yet completed a reboot/autostart/restart acceptance test.
- Camera disconnect/reconnect behavior has not been tested on the target.
- Sustained capture FPS and p50/p95 latency have not been measured over a representative run.
- Detection quality has not been characterized for range, angle, motion blur, exposure, partial occlusion, and field lighting.
- The 30-minute thermal/reliability test and two-camera test have not been run.
- Network setup was intermittently affected by DHCP/mDNS connectivity during deployment and should be confirmed before relying on remote administration or NT.
- RoboRIO integration, fusion, uncertainty tuning, Limelight fallback, and production rollout remain explicitly deferred.
- Imported dependency licensing and distribution details should receive a final review before release.

## Recommended Next Steps

### Priority 0: Make the current proof reproducible

- [x] Remove the temporary credential-bearing deployment helper.
- [x] Review and commit the intentional Jetson build/configuration changes.
- [x] Keep CCCL checkouts and wheelhouses out of Git as regenerable local caches.
- [ ] Record the exact supported V4L2 modes and controls for the attached camera.
- [ ] Run a 2–5 minute probe and save structured output with detection FPS, processing latency, overwrites, and errors.
- [ ] Confirm clean shutdown and restart after camera and service interruption.

### Priority 1: Establish trustworthy pose output

- [ ] Calibrate the OV2311 in its final focus and exact operating mode.
- [ ] Validate the calibration file with the CLI and confirm its camera identity and dimensions.
- [ ] Measure and configure the camera-to-robot transform.
- [ ] Load the intended WPILib field layout and lock its expected revision.
- [ ] Test a known tag at measured poses and compare translation, rotation, and reprojection error.
- [ ] Verify both single-tag IPPE candidates and multi-tag pose refinement.
- [ ] Confirm that unknown tags remain in raw observations but do not affect field-relative pose.

### Priority 2: Validate transport and service operation

- [ ] Enable NT4 against a local or robot-like server and inspect every `/Buddy/...` topic.
- [ ] Verify capture timestamps, ordered/duplicate/empty frames, revisions, latency fields, FPS, drops, state, and errors.
- [ ] Install the systemd service under the unprivileged account and verify startup after reboot.
- [ ] Test camera unplug/replug and network interruption without restarting the whole device.
- [ ] Run the 30-minute thermal and reliability test and record p50/p95 timing and frame-drop results.

### Priority 3: Prepare for robot shadow testing

- [ ] Freeze a repeatable camera mode and exposure profile based on field-like measurements.
- [ ] Validate the physical camera mount and transform on the robot.
- [ ] Publish observations in shadow mode without using them for control.
- [ ] Compare Buddy output with the robot's existing vision and odometry logs.
- [ ] Begin roboRIO integration and fusion only after the Jetson pose and transport gates pass.

## Milestone Gates

| Milestone | Status | Completion evidence |
| --- | --- | --- |
| Build native extension on Jetson | Complete | CUDA detector loads and runs on `orin-1` |
| Capture frames from target camera | Complete | OV2311 live frames reach the detector |
| Detect a known raw tag | Complete | Correct ID, zero hamming, strong margin, valid corners |
| Reproduce and benchmark raw detection | In progress | Sustained probe log and latency distribution needed |
| Produce calibrated camera pose | Pending | Calibration and measured pose tests needed |
| Publish and receive complete NT4 contract | Pending | End-to-end subscriber validation needed |
| Survive deployment/reconnect/endurance tests | Pending | systemd, unplug, reboot, and 30-minute tests needed |
| Robot shadow validation | Deferred | Begins after Jetson-side gates pass |

## Updating This Document

Update the date and overall status whenever a milestone changes. For each completed gate, link or name the relevant configuration, calibration, test log, replay dataset, or benchmark result. Keep implementation claims separate from hardware-validated claims so this document remains a reliable handoff and readiness record.
