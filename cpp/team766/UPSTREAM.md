# Team 766 CUDA AprilTag provenance

- Upstream: https://github.com/Team766/apriltags_cuda
- Imported commit: `65366174d5e735bf6d71e34328b2a064e16bffb4`
- Commit date: 2025-07-08
- Original description: standalone extraction of Team 971's CUDA AprilTag detector for NVIDIA Jetson Orin processors.

## Imported code

Buddy retains the detector, CUDA utilities, thresholding, connected-component
labeling, point collection, line/quad fitting, AprilTag decode integration, and
the associated headers. The upstream GPU test and its two input images are also
retained outside this directory.

## Buddy changes around the implementation

The upstream application, OpenCV GUI demos, websocket server, NetworkTables
senders, camera wrapper, and obsolete dependency download graph are omitted.
Buddy supplies its own CMake target and a pybind11 boundary. The imported CUDA
algorithm files are otherwise intentionally kept recognizable so changes can be
audited against the pinned revision.

`apriltag_utils` was reduced to tag-family lifecycle helpers so the detector
library no longer depends on the removed OpenCV GUI drawing functions.

The upstream repository does not contain a single root license file at this
revision. Copyright and license notices embedded in individual sources are
preserved. Confirm redistribution terms before distributing binaries outside
Team 581.

The required Team 766 AprilTag fork is vendored under `cpp/apriltag` and pinned
at commit `67c0f842a1c24fb6a7527eba77cd5c10135cf8e6` (tag `3.3.0`). Its BSD-2-Clause
license is retained in that directory.

As in Team 766's build, NVIDIA CCCL 2.3.2 is required. CMake pins commit
`64d3a5f0c1c83ed83be8c0a9a1f0cdb31f913e81`; an existing checkout can be
supplied with `BUDDY_CCCL_ROOT` to make builds network-independent.
