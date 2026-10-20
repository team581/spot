---
title: 'Faults and coordinates'
---

Match the robot's rejection code to the next check, or look up coordinate and trust conventions.

## Rejection lookup

| Code                                          | Check next                                                         |
| --------------------------------------------- | ------------------------------------------------------------------ |
| `SCHEMA` / `MALFORMED`                        | Packet version, shape and bounds                                   |
| `CONFIGURATION` / `CALIBRATION`               | Session, field, binding, active intrinsics and mode                |
| `TIMESTAMP` / `STALE` / `FUTURE`              | Capture clock domain, timing quality and frame age                 |
| `DUPLICATE` / `OLD_EPOCH` / `RESET`           | Frame identity and reset boundary                                  |
| `HISTORY` / `MOUNT_HISTORY`                   | Available robot or moving-mount history at capture time            |
| `UNKNOWN_TAG` / `FIELD_BOUNDS` / `ROBOT_TILT` | Field layout, measured mount and pose geometry                     |
| `AMBIGUOUS`                                   | Whether capture-time heading decisively resolves IPPE alternatives |
| `RESIDUAL` / `INNOVATION`                     | Image residual or disagreement with the pre-fusion estimate        |
| `NO_TAGS`                                     | Normal when a fresh valid frame contains no tags                   |

Check the camera page for the frame's validation/fusion decision. If the connection or clock is failing, use [Network and power recovery](../recovery/).

## Coordinate quick reference

| Quantity             | Convention                                                        |
| -------------------- | ----------------------------------------------------------------- |
| Robot axes           | WPILib NWU: +X forward, +Y left, +Z up                            |
| Translation / angles | Metres / right-handed rotation                                    |
| Pitch                | Positive points the forward lens down; negative points it up      |
| Wire quaternion      | W, X, Y, Z                                                        |
| Wire pose            | Field-to-camera                                                   |
| Field origin         | Blue-wall-right, fixed across alliance changes                    |
| OpenCV camera axes   | +X right, +Y down, +Z forward; converted explicitly by the solver |

The robot recovers field-to-robot with:

```text
fieldToRobot = fieldToCamera * inverse(robotToCamera)
```

Use the [Geometry guide](../geometry/) for visual mount inspection.

## Confidence and trust

Translation uncertainty accounts for distance, geometry, image residual, and motion × timestamp uncertainty, with positive conservative floors. Cameras seeing the same tags close in time are correlated; extra observations are not automatically independent evidence.

> **Heading remains suppressed.** It uses a large finite supported deviation until its separate review gate passes. Revised trust also remains behind a reviewed feature flag.

<details>
<summary>Capture-time trust and reset rules</summary>

Revised trust evaluates observations at their capture time before fusion, degrades with odometry travel, elapsed time and collisions, and uses a consistent reset baseline. Empty measurement lists never sample pose history at NaN. Missing capture-time history is never concealed by substituting the current pose.

</details>
