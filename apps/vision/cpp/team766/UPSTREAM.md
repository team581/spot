# Team 766 CUDA AprilTag provenance

- Upstream: https://github.com/Team766/apriltags_cuda
- Imported commit: `65366174d5e735bf6d71e34328b2a064e16bffb4`
- Commit date: 2025-07-08
- Original description: standalone extraction of Team 971's CUDA AprilTag detector for NVIDIA Jetson Orin processors.

## Imported code

Spot retains the detector, CUDA utilities, thresholding, connected-component
labeling, point collection, line/quad fitting, AprilTag decode integration, and
the associated headers. The upstream GPU test and its two input images are also
retained outside this directory.

## Spot changes around the implementation

The upstream application, OpenCV GUI demos, websocket server, NetworkTables
senders, camera wrapper, and obsolete dependency download graph are omitted.
Spot supplies its own CMake target and a pybind11 boundary. The imported CUDA
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

CCCL is provided by the CUDA toolkit package (`cudaPackages.cuda_cccl` in Nix)
and discovered with `find_package(CCCL CONFIG REQUIRED)`. Spot no longer downloads
a separate CCCL checkout.

## Distortion regression corrections

Spot extracted the host edge geometry from `apriltag_detect.cu` into
`camera_geometry.h`, shared by the CUDA decoder and host diagnostics. Gradient
samples are undistorted before line fitting; line intersections are redistorted
before decoding and publication. The imported inverse's p2 term was corrected
from `rSq + k3*rSq^3` to `rSq + 2*x^2`, matching the forward Brown-Conrady model.
Inversion now checks convergence in pixels and preserves input on failure.
Refinement skips unusable samples and retains the original quad when an edge
cannot be fitted. Tests compare the shared code against OpenCV projections and
fixed images. These are intentional local changes to the pinned import.

CPU detection uses the published RobotPy AprilTag bindings on both host and
Jetson. Optional host diagnostics exercise the shared CUDA geometry without
compiling the vendored detector. The family lifecycle utility no longer needs glog. The vendored workerpool header now
includes its pthread declarations explicitly so it builds on macOS as well.
