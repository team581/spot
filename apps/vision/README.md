# Spot vision service

Python owns camera capture, scheduling, pose solving, NetworkTables, and HTTP.
The C++/CUDA detector builds as part of this Python package.

From the repository root, run `mise run setup` for a CPU development build or
`mise run setup:jetson` for CUDA on the Jetson. Run commands with
`uv run --package spot-vision spot-vision --help`.

The uv workspace shares the root `.venv` and `uv.lock`. The dashboard and operator
docs are separate applications bundled into the installed wheel by CMake.
See the [repository guide](../../README.md) for setup, testing, and deployment.
