# Spot vision service

Python owns camera capture, scheduling, pose solving, NetworkTables, and HTTP.
CPU detection uses the published `napa-vision` package. The C++/CUDA detector
builds only with `SPOT_BUILD_CUDA=ON`; host geometry tests use
`SPOT_BUILD_DIAGNOSTICS=ON`.
NAPA supports all upstream AprilTag families, including `tag36h11` (Spot's FRC
family). CPU detection uses `family`, `max_hamming`, `min_tag_px` (default 16
for distant tags), and `min_contrast` (default 3 to retain tags in the dark alpha
camera fixtures). Raising `min_tag_px` to 32 or `min_contrast` toward NAPA's
default 20 reduces CPU work at the cost of small or low-contrast tag detection.
NAPA runs one thread per detector and always refines edges;
`decimate`, `blur`, `threads`, and `refine_edges` apply only to CUDA.
The CPU adapter preserves upstream AprilTag corner order and pixel coordinates
for the shared pose solver. Python 3.11 or newer is required.

From the repository root, run `mise run setup` for CPU development or
the [NixOS configuration](../../nix/README.md) for CUDA on the Jetson. Run commands with
`uv run --package spot-vision spot-vision --help`.

The uv workspace shares the root `.venv` and `uv.lock`. The dashboard and operator
docs are separate applications bundled into the installed wheel by CMake.
See the [repository guide](../../README.md) for setup, testing, and deployment.
