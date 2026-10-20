---
title: 'Camera tuning'
---

Adjust the live image and check what the camera actually accepted. Eligible slider changes apply immediately.

## Open a camera

For a configured camera, disable the connected robot. Without a profile, open the USB feed and click **Open standalone camera setup**. After a service restart, use **Enable standalone setup** to authorize edits again.

![Camera Config panel with live exposure, gain and brightness controls](../../../assets/docs-images/camera.png)

_Config shows the available controls beside the feed. Demonstration values are examples, not recommended presets._

## Tune and confirm

1. Check **Capture resolution / rate** matches the intended optical mode.
2. Adjust an eligible slider while watching the image.
3. Wait for the pending request to finish and check the actual device readback.
4. Use undo/redo to compare changes, or **Reset to code defaults** to restore the robot policy.

| Setting                     | Useful first check                                                                    |
| --------------------------- | ------------------------------------------------------------------------------------- |
| Exposure                    | Shorter reduces motion blur; longer collects more light. Values are in µs.            |
| Gain                        | Brightens the image but can increase noise. Use the device's advertised scale.        |
| Automatic controls          | Disable the relevant automatic mode before setting manual values.                     |
| Policy lock                 | Explicitly pinned controls follow robot code; omitted controls keep saved GUI values. |
| Rejected or clipped request | Read the reason; the previous acknowledged setting stays active.                      |

Acknowledged GUI values are saved on the Jetson and restored after restart. Omitting a control from Java leaves it under GUI control; adding a pinned entry takes authority again. **Reset to code defaults** resets controls with tunable Java defaults and leaves omitted controls unchanged.

There is no tuning **Save** or **Apply** button. For exact control names and values, see [Cameras in Java](../camera-configuration/).

> **Optical changes affect calibration.** Focus, zoom, crop, rotation and flip can invalidate intrinsics. Capture mode and control readback also affect measured timing. Revalidate the applicable evidence before robot use.

## Frame rate and latency

Capture FPS and processing FPS are separate. Use a supported capture mode, then compare delivered updates, p95/p99 latency, worst-case age and gaps. Higher FPS is useful only if the system keeps up.

On the three-camera bench, **640 × 480 MJPEG at 120 capture FPS with a 30 FPS processing cap** delivered about 28 detections per second per camera. The 20/30/45 cap comparison had similar robot receipt p95 (about 41–44 ms); 45 repeatedly triggered load reduction, so 30 preserves more headroom. These are bench measurements from read completion, not sensor exposure, and the cameras were not yet calibrated for live pose solving. Recheck after calibration and under the robot's actual workload.

A low p95 does not rule out an outage. Clock renewal caused longer delivery gaps; the faster robot profile announcement reduced recovery time, but timing qualification is still required. Stale or invalid observations must remain rejected.

<details>
<summary>Exposure limits</summary>

Exposure must fit one configured capture interval and the driver's supported range and step. At 120 FPS with 100 µs steps, the maximum is 8,300 µs. The driver maximum remains in the tooltip. This limit follows capture FPS, not detection or preview FPS. Requests above it are rejected; if the minimum is too long, choose a lower supported rate.

</details>

<details>
<summary>History, standalone settings and other browsers</summary>

One acknowledged slider gesture is one undo entry; reset is one transaction. Failed writes add no history, and a new change clears redo. Another browser's revision invalidates local history: click **Reconcile current values** before editing again.

Standalone settings persist by physical identity. **Reset setup values** returns to the values captured when setup first opened. Its 3D origin is an inspection reference. Connecting a robot ends standalone authorization; robot bindings, transforms and policy remain authoritative. Enable, unknown state or link changes can reject a pending write.

Advanced **Copy settings as code** produces policy helpers for review; it does not create camera definitions.

</details>
