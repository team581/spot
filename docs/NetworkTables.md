# NetworkTables transport

Spot uses WPILib structs and native NetworkTables values. The roboRIO runs the
NT4 server and Spot connects as a client. There is one current contract under
`/Spot`; upgrades update both ends together.

| Topic                                                | Type                                                   | Publisher |
| ---------------------------------------------------- | ------------------------------------------------------ | --------- |
| `/Spot/<camera>/observations`                        | `struct:SpotFrameResult`                               | Spot      |
| `/Spot/health`                                       | `struct:SpotHeartbeat`                                 | Spot      |
| `/Spot/robot/state`                                  | `struct:SpotRobotStatus`                               | Robot     |
| `/Spot/robot/profile/field/tags`                     | `struct:SpotFieldTag[]`                                | Robot     |
| `/Spot/robot/profile/cameras/<name>/robot_to_camera` | `struct:Transform3d`                                   | Robot     |
| `/Spot/robot/profile/...`                            | Strings, numbers, booleans and string arrays           | Robot     |
| `/Spot/robot/session`                                | String                                                 | Robot     |
| `/Spot/robot/manifest`                               | Profile fingerprint string, refreshed during handshake | Robot     |
| `/Spot/config/acknowledgement/...`                   | Strings, integers, booleans and string arrays          | Spot      |
| `/Spot/config/ack`                                   | Acknowledgement fingerprint string                     | Spot      |

Python structs are ordinary dataclasses decorated with `make_wpistruct` in
`apps/vision/src/spot_vision/structs.py`. Java uses small records with WPILib
`Struct` implementations in `frc.robot.vision.structs`. Geometry uses WPILib's
existing `Pose3d` and `Transform3d` layouts. NT publishes the
schemas automatically. No generated bindings or schema compiler are required.

## Frames

`SpotFrameResult` is one 328-byte NT value: context and capture identifiers,
sequence, requested tag-selection generation, diagnostic capture time,
timestamp source and uncertainty, observed tags, two pose slots, and timings.
`candidateCount` selects zero, one or two pose slots. An empty frame still
advances the sequence and supplies camera-health evidence.

Each pose slot contains `Pose3d`, solve method, tag mask, reprojection error,
average distance, image area/spread and distortion displacement. The methods
are 1 for multi-tag SQPNP and 2 for single-tag IPPE. Timestamp sources are 1 for
read completion, 2 for exposure start and 3 for exposure end, in the local NT
clock domain.

Tag masks index the ordered field-tag list in the acknowledged profile, allowing
up to 64 arbitrary tag IDs. Bit 63 is represented by a signed Java/Python int64.
Unknown detections remain available locally; only configured tags enter robot
pose results. Corners and textual rejection diagnostics stay on Spot.

The two context int64s identify the complete acknowledgement plus camera name.
The robot resolves them against cached metadata. Frames carry no repeated names,
hash strings, calibration descriptions or camera configuration.

Publish at the explicit capture timestamp with `sendAll` and `keepDuplicates`.
The robot drains the queue and uses the NT envelope's verified server/FPGA
timestamp. The local time inside the struct is diagnostic. Reset, disconnect,
session/configuration changes and expired synchronization invalidate old frames.

The Java adapter reads the raw NT queue and uses WPILib `StructBuffer` to decode
each entry. This preserves valid frames when another entry is malformed:
NTCore 2026's typed struct queue reader incorrectly discards the entire batch in
that case. The published type remains `struct:SpotFrameResult`.

## Configuration and acknowledgements

The robot publishes its profile through typed topics. Camera and mode names and
control names enumerate their respective sections. Field tags use a struct array;
camera mounts use `Transform3d`. The complete profile fingerprint and current
robot session establish the handshake. Spot applies a profile only when the
received values reproduce its fingerprint, so partially delivered sections cannot
be applied as a complete profile.

Acknowledgements use the same rule: Spot publishes metadata and then its complete
fingerprint. The robot accepts only a matching snapshot for its current session
and profile. It calculates frame contexts once per acknowledgement.

Fingerprints hash ordered record fields: UTF-8 strings and lists have uint32
length prefixes; integers are int64, booleans are one byte, and floating-point
values are float64, all little endian. Pose quaternion components are rounded
to 12 decimal places for fingerprints because WPILib normalizes them during
geometry decoding. Wire geometry retains float64 precision.

JSON profile snapshots are local Jetson storage and desktop test inputs. The
roboRIO does not parse JSON to receive configuration or vision results.

## Local diagnostics

Config-file camera and recording commands run locally without publishing NT
topics. Fixed-image regression serializes the same frame structs as the installed
service. Live `probe` uses the same bounded V4L2 capture owner.

The browser continues to use the Jetson's HTTP/JSON API. It does not decode NT
structs.
