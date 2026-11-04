# Spot transport schemas

`vision.proto` is the historical alpha v1 contract. Production beta uses
`vision_v2.proto`, package `spot.vision.v2`, on `/Spot/v2/…` topics. A v1 display
pose is never a v2 robot measurement.

Generate both languages with the same official protoc 33.2 compiler:

```sh
protoc -I proto --python_out=apps/vision/src/spot_vision/proto apps/vision/proto/vision_v2.proto
mkdir -p /tmp/spot-java
protoc -I proto --java_out=/tmp/spot-java apps/vision/proto/vision_v2.proto
# Preserve the extraction marker on every generation/copy:
python3 - <<'PYTHON'
from pathlib import Path
source = Path('/tmp/spot-java/frc/robot/vision/generated/SpotProtos.java')
target = Path('../offseason-2026/offseason-bot/src/main/java/frc/robot/vision/generated/SpotProtos.java')
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text('// Move to shared folder after offseason\n' + source.read_text())
PYTHON
PYTHONPATH=apps/vision/src:apps/vision/tests .venv/bin/python apps/vision/tools/generate_beta_fixtures.py
cp apps/vision/tests/data/beta/* ../offseason-2026/offseason-bot/src/test/resources/spot-beta/
```

The Java namespace is `frc.robot.vision.generated`; generated code is excluded
from formatting. Java runtime protobuf 4.33.2 belongs to offseason-bot as an
implementation dependency. Shared and other robot modules do not depend on Spot.
Python requires the declared runtime (also supporting the existing v1 file).
Legacy fixtures remain byte-identical; policy fixtures separately pin bytes and
SHA-256 hashes. Include both schemas in releases.

Profile hashing is SHA-256 of serialized `Profile` bytes; no map fields occur.
Preserve explicit repeated-field order. Manifest sessions are deliberately
outside the content hash: new code sessions must handshake even for equal content.
Robot code owns field/mount/policies. Saved bindings are per robot ID, and
calibration is per physical identity plus exact optical mode signature.

Poses use WPILib NWU, metres, WXYZ normalized quaternions; `field_to_camera` is
the camera pose in the configured blue-wall-right field. Robot pose is
`field_to_camera × inverse(robot_to_camera)` at capture time. Reprojection error
is RMS Euclidean corner residual in delivered-image pixels. Area is the summed
used-tag quadrilateral area / image area (bounded at 1); spread is the used-corner
bounding rectangle / image area. Distortion displacement is diagnostic only.

Jetson publishes observations with an explicit **local NT** capture timestamp.
NT4 converts it to the server clock. Robot consumes the NT envelope timestamp
in FPGA seconds, then calls `Utils.fpgaToCurrentTime` once at the CTRE boundary.
The local timestamp inside protobuf is a diagnostic, never an FPGA timestamp.
`TimestampedRaw.serverTime` sentinels 0/1 use local time only on a verified NT
server; conflicting domains are rejected. Real-roboRIO evidence remains required.

NTCore 2026.2.2's `ClientImpl` handles the initial RTT reply once per connection;
it does **not** periodically emit fresh time-sync updates. A loopback experiment
confirmed no new update after six seconds. Beta defaults to a 30-second sync-age
limit and requests a fresh built-in NT exchange by reconnecting at expiry.
This limit and its recovery interruption require hardware drift/load qualification.
Offset polling never extends exchange validity. ±5 ms discontinuity and 5 ms
half-RTT bounds are engineering gates, not measured accuracy claims.

Each connection/sync/capture/service epoch and runtime generation invalidates old
frames. No tags still produces empty observations with advancing sequence.
Uncalibrated cameras retain diagnostics but have no production candidates.
Clock Waiting/Invalid withholds all robot observations while local operation
continues. Max packets are 64 KiB / 2 candidates / 64 tags; profiles are 256 KiB,
32 cameras and 64 field tags. Protocol bounds do not certify hardware capacity.

Sources: [WPILib timestamp domains](https://docs.wpilib.org/en/stable/docs/software/networktables/networktables-intro.html#timestamps),
[TimestampedRaw sentinels](https://github.wpilib.org/allwpilib/docs/release/java/edu/wpi/first/networktables/TimestampedRaw.html),
[NTCore 2026.2.2 source](https://github.com/wpilibsuite/allwpilib/blob/v2026.2.2/ntcore/src/main/native/cpp/net/ClientImpl.cpp).


## Runtime tag selection (service 0.2.1 / offseason local integration)

Schema v2 and existing topics/field numbers remain unchanged. New fields are
RobotState `tag_selection_generation=4`, `allowed_tag_ids=5`, Acknowledgement
`tag_selection_supported=13`, and Observation `tag_selection_generation=25`.
The namespace option changes generated Java paths only, never packet bytes or
profile hashes. `revised_trust_enabled` advertises the installed local trust
model; it no longer selects between two offseason implementations.

A positive generation scopes sorted, unique field IDs to the current robot
session. Only increasing fresh robot-state sequences can refresh it. Equal
selection generations must keep identical IDs; lower generations cannot replace
a newer selection. Enabled-time selection never unlocks calibration, bindings,
mounts or controls. Disconnect, manifest/session replacement or freshness expiry
withholds policy-qualified observations until a fresh matching request arrives.
The robot requires advertised support and rejects older applied generations and
candidate IDs outside its selection independently.

Detection runs once. The frame processing snapshot filters detections before
pose solving, preserves excluded diagnostics (`tag-policy-excluded`), and emits
an advancing no-pose observation for an empty selected set. Publication rechecks
the current policy so in-flight solves cannot be relabeled after a change.
There is no capture/detector restart or manifest mutation for tag selection.

## Python type stubs

The `.pyi` files beside the generated Python messages describe their dynamic
fields for `ty`. Regenerate them from the repository root without changing the
runtime `.py` files:

```sh
uv tool run --from grpcio-tools==1.85.1 --with mypy-protobuf==5.1.0 python -m grpc_tools.protoc \
  -I apps/vision/proto --mypy_out=apps/vision/src/spot_vision/proto \
  apps/vision/proto/vision.proto apps/vision/proto/vision_v2.proto
```

The workspace's development dependencies include the matching `types-protobuf`
annotations used by these generated stubs.
