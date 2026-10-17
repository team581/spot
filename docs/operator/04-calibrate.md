Title: 4. Calibrate
Group: Getting started

# Calibrate

## Board and prerequisites

Verify a live preview first. A robot profile or camera name is not required: open the camera and choose **Open standalone camera setup**, or add the connected camera directly on Calibration. Standalone setup saves tuning and intrinsics against the physical device and optical mode. Its displayed origin is only an inspection reference, not a robot mount. Use the measured printed board: 15 × 15 squares, 30 mm square length, 22 mm marker length, DICT_4X4_250. Confirm the actual print scale; changing print settings can change these dimensions. Intrinsic calibration does not determine the robot mount.

Open Calibration and enter the explicit board values, lens model and minimum fit views. Defaults are persisted through the configuration service. The fitting baseline is at least 15 sharp views with sufficient coverage and diversity. The production CUDA edge-refinement implementation supports the five-coefficient model; incompatible higher-order models cannot be silently truncated.

## Fitting captures

1. Add the connected cameras to Calibration. Unconfigured cameras use their persistent USB labels. One board can move between cameras; simultaneous visibility is unnecessary.
2. Choose **Fitting captures**, then **Start**. Automatic capture rejects duplicate views and guides you toward unobserved coverage regions. **Capture** explicitly accepts the current new board frame; **Pause** affects calibration capture.
   To start the entire selected group, choose **Group capture set** in Board and click **Start automatic capture**. The backend checks every selected camera before starting any of them. Use **Pause all** to stop the group.
3. Move, tilt and change the board distance. Registered coverage particles are guidance, not a quality certificate. Keep the image sharp and vary scale and tilt as well as position.
4. Click **Calibrate** for each camera. Solves run in the background while the other cameras and navigation remain usable. A failure retains the active calibration.

## Separate validation captures

1. After fitting, select **Validation captures** and **Start**. These new captures are stored separately and are never used to refit intrinsics.
2. Capture at least five independent diverse views. The worker rejects reused frame identities and caps validation at 20 views.
3. Click **Validate**. Intrinsics remain fixed while board extrinsics are solved for each held-out view. Independent corner RMS must meet the configured limit, at most 0.8 px.
4. Open **Results / history**. Review fit RMS, independent validation RMS, both view counts and the specific pass/retry reason.

## Apply and restore

Select the intended complete group and click **Apply selected** only when every selected camera passes. **Select passing** is an explicit way to choose a smaller passing group. The backend validates the whole group, stages an immutable generation, rebuilds detector/solver state, discards prior-generation frames, and activates its pointer atomically. **Applied** appears after durable runtime acknowledgement.

If any selected member or write fails, none of that group activates. History lists activated generations and optical compatibility. Select compatible camera records and use **Restore selected**. It uses the same disabled/standalone eligibility and atomic application checks. Recalibrate after replacement, lens/focus/crop/flip changes or an incompatible optical mode. Earlier complete generations remain available for recovery.
