---
title: Java client
description: The com.team581.spot vendordep.
---

Vendordep URL: `https://spot.frc581.com/vendordep.json`.
Maven coordinates: `com.team581:spot`, on Maven Central.

All classes are in `com.team581.spot`.

## `Spot`

Publishes the config and field layout, and reads Spot's status. `AutoCloseable`.

| Member                                                                          | Description                                                                              |
| ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `Spot(String config, AprilTagFieldLayout fieldLayout)`                          | Connects on the default NetworkTables instance. `config` is the contents of `spot.toml`. |
| `Spot(NetworkTableInstance nt, String config, AprilTagFieldLayout fieldLayout)` | Connects on `nt`.                                                                        |
| `SpotCamera camera(String name)`                                                | The camera with this name in `spot.toml`.                                                |
| `Optional<SpotStatus> status()`                                                 | Latest status; empty while Spot isn't connected.                                         |
| `String error()`                                                                | Details for a non-`READY` state; empty when ready.                                       |

## `SpotCamera`

One camera's estimates and status. `AutoCloseable`.

| Member                                                    | Description                                                                                                 |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `String name()`                                           | The camera's name.                                                                                          |
| `void onEstimate(Consumer<TimestampedEstimate> callback)` | Calls `callback` for each estimate, on the NetworkTables listener thread. The callback must be thread-safe. |
| `Optional<SpotCameraStatus> status()`                     | Latest status; empty while Spot isn't publishing it.                                                        |

## `TimestampedEstimate`

`record TimestampedEstimate(double timestampSeconds, SpotEstimate estimate)`

`timestampSeconds` is the frame's capture time in FPGA seconds.

## `SpotEstimate`

`record SpotEstimate(Candidate primary, Optional<Candidate> alternate, int[] tagIds, double averageTagDistance, double tagArea)`

| Component            | Description                                |
| -------------------- | ------------------------------------------ |
| `primary`            | Best-fitting robot pose.                   |
| `alternate`          | Second plausible robot pose.               |
| `tagIds`             | IDs of the tags used, ascending.           |
| `averageTagDistance` | Average camera-to-tag distance, in meters. |
| `tagArea`            | The tags' share of the image area, 0 to 1. |

`record Candidate(Pose3d pose, double error)`: a field-relative robot pose and its RMS reprojection error in pixels.

## `SpotStatus`

`record SpotStatus(String version, State state, boolean overridesActive)`

`State`: `READY`, `WAITING_FOR_TIME_SYNC`, `WAITING_FOR_CONFIG`, `INVALID_CONFIG`, `MISSING_CAMERA`, `UNCALIBRATED_CAMERA`, or `UNKNOWN` for a state from a newer Spot.
See [NetworkTables](../networktables/#spotstatus) for meanings.

## `SpotCameraStatus`

`record SpotCameraStatus(State state, double fps, long droppedFrames)`

`State`: `STREAMING`, `DISCONNECTED`, `DUPLICATE_SERIAL`, `UNCALIBRATED`, `FALLING_BEHIND`, or `UNKNOWN`.
See [NetworkTables](../networktables/#spotcamerastatus) for meanings.

## Example

```java
var spot = new Spot(
    Files.readString(Filesystem.getDeployDirectory().toPath().resolve("spot.toml")),
    AprilTagFieldLayout.loadField(AprilTagFields.kDefaultField));
spot.camera("front").onEstimate(sample -> drivetrain.addVisionMeasurement(
    sample.estimate().primary().pose().toPose2d(),
    Utils.fpgaToCurrentTime(sample.timestampSeconds()),
    stdDevs));
```

CTRE's `SwerveDrivetrain.addVisionMeasurement` is thread-safe.
WPILib's pose estimators are not.
