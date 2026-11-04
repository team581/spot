# Spot vision service

Python owns camera capture, scheduling, pose solving, NetworkTables, and HTTP.
CPU detection uses the published `robotpy-apriltag` package. The C++/CUDA detector
builds only with `SPOT_BUILD_CUDA=ON`; host geometry tests use
`SPOT_BUILD_DIAGNOSTICS=ON`.
RobotPy supports `tag36h11` (Spot's FRC family) and `tag16h5` for CPU detection.

From the repository root, run `mise run setup` for CPU development or
the [NixOS configuration](../../nix/README.md) for CUDA on the Jetson. Run commands with
`uv run --package spot-vision spot-vision --help`.

The uv workspace shares the root `.venv` and `uv.lock`. The dashboard and operator
docs are separate applications bundled into the installed wheel by CMake.
See the [repository guide](../../README.md) for setup, testing, and deployment.
