Title: 5. Verify detections
Group: Getting started

# Verify detections

## Inspect local output

Open Overview. Detection FPS means usable detector/solver output cadence; it is separate from browser preview rate and capture FPS. Zero tags on a current frame is normal. Missing metrics use —. Frame age continues advancing after a stall, and stale images lose detection outlines.

Open a camera. **Show detection outlines** shows boundaries and IDs for the displayed frame. **Pause image** freezes only that inspection image; processing and publication continue. Resume requests fresh frames. The Detections table and expandable candidates refer to the same shown frame.

The blue 3D candidate is the local lowest-image-error selection; amber shows alternatives. The robot independently validates candidates using capture-time pose/mount history, tag geometry, field bounds, timestamp quality and innovation. A local solved pose does not prove robot acceptance.

## Check robot decisions

The camera page shows robot validation and fusion separately. Decisions identify their frame and capture epoch; unavailable robot feedback is explicit. Translation-only behavior, fusion off and revised trust off are the defaults. IPPE ambiguity requires a decisive capture-time heading advantage; no arbitrary minimum-image-error choice is fused.

## Qualify hardware before fusion

Record the beta plan's real Jetson/roboRIO acceptance evidence: FPGA timestamp domains and sentinels, sensor-to-read delay and uncertainty, four-camera throughput and age, image/pose accuracy, USB/Ethernet outages, independent boot orders, abrupt power loss, recovery and rollback. CPU simulation and fixture screenshots are software evidence only.

Capture timing stays unqualified until a measured record matches the physical identity, exact mode and current control readback. System's support bundle includes the signature. Submit an explicitly measured timing record through the API while disabled; changing mode or controls invalidates it. Never enter zero uncertainty or adjust timestamps to hide a clock error.

Fusion and revised trust remain off in offseason FeatureFlags and in the profile until the team approves the review gates and the hardware trials pass.
