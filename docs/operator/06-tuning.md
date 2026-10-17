Title: Camera tuning
Group: Guides

# Camera tuning

## Standalone camera setup

A camera does not need a robot profile for tuning or calibration. Open its camera page and choose **Open standalone camera setup**. The normal feed, live controls, undo/redo, mode selection and calibration become available. A warning identifies the unconfigured camera; its 3D inspection model starts at (0, 0, 0) with zero rotation. Settings persist by physical identity. **Reset setup values** restores the device values captured when standalone setup was first opened.

After a service restart, the feed remains accessible; click **Enable standalone setup** to authorize edits again. Connecting a robot ends standalone authorization. Robot-defined camera bindings, mount transforms and control policies retain authority for configured cameras. A connected robot must be freshly disabled before edits are allowed.

## Live requested and readback values

Config displays actual advertised controls, units, ranges, steps, menus and policy locks. Exposure time controls use microseconds in robot policy and API, converting native UVC 100 µs units explicitly. Gain units are shown only when advertised; no universal dB range is assumed.

The exposure slider is limited to one configured capture interval, rounded down to the driver's supported step. At 120 FPS with 100 µs steps its maximum is 8,300 µs. The driver-advertised maximum remains in the tooltip; the limit changes with capture mode and is independent of detection or preview FPS. A direct tuning request above the frame limit is rejected rather than silently clipped. If the camera's minimum exposure exceeds the interval, choose a lower capture rate.

Drag an eligible slider. Requests are bounded and the final gesture value is delivered after pending samples. The requested value, pending state and actual device readback are distinct. A clipped or rejected write retains the previously acknowledged configuration and shows the attempted value and reason. There is no tuning Save or Apply action.

## History and concurrency

A complete acknowledged slider gesture is one undo entry. Reset to code defaults is one acknowledged transaction. Failed writes do not add entries; redo clears after a new change. Undo/redo use the same backend validation, revision and eligibility checks.

Another browser's revision invalidates local history. **Reconcile current values** reloads current acknowledged settings before another edit; it never replays stale snapshots silently. Robot enable, unknown enabled state or link changes can reject a pending mutation at commit. Read-only previews remain available.

## Optical and timing effects

Focus, zoom, crop, rotation, flip and similar optical controls invalidate intrinsic compatibility when changed. Measured capture timing also depends on exact mode and control readback. Requalify the applicable calibration and timing before robot use. Advanced **Copy settings as code** outputs the current policy helpers for robot code review; it does not create camera definitions.
