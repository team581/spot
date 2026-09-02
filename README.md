# Buddy Vision

Buddy Vision is Team 581's Jetson Orin AprilTag service. Python owns camera
capture, scheduling, pose solving, NetworkTables, health, and deployment. The
CUDA detector is a direct, attributed import of Team 766's standalone Team 971
implementation, exposed to Python through pybind11.

The full design contract is in
[`docs/Vision Solution (Buddy) Specs.md`](docs/Vision%20Solution%20(Buddy)%20Specs.md).
This first pass intentionally has no GUI and makes no roboRIO changes.

## Jetson prerequisites

- JetPack with CUDA development tools and compute capability 8.7 support
- Python 3.10 or newer
- CMake 3.24+, Ninja, a C++20 compiler, `libgoogle-glog-dev`, and `libgflags-dev`
- GStreamer with V4L2, JPEG decode, and OpenCV GStreamer support
- `v4l-utils`

On Ubuntu/Jetson, install the system prerequisites:

```sh
sudo apt install cmake ninja-build python3-dev python3-venv \
  libgoogle-glog-dev libgflags-dev v4l-utils \
  gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad
```

Build and install into a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
CMAKE_ARGS="-DBUDDY_CUDA_ARCHITECTURES=87" .venv/bin/pip install -e '.[test,systemd]'
```

The CUDA build downloads the pinned CCCL 2.3.2 headers. For an offline build,
pre-clone that revision and add `-DBUDDY_CCCL_ROOT=/path/to/cccl` to
`CMAKE_ARGS`.

For a host-only Python installation that deliberately omits CUDA:

```sh
CMAKE_ARGS="-DBUDDY_BUILD_CUDA=OFF" .venv/bin/pip install -e '.[test]'
```

## First camera test

Edit `config/buddy.json` with the camera's persistent `/dev/v4l/by-id` name,
then enumerate what the driver actually supports:

```sh
.venv/bin/buddy-vision camera-modes --config config/buddy.json --camera front
```

Run the headless proof. Each output line contains tag IDs, corners, hamming,
decision margin, FPS, timing, and drops:

```sh
.venv/bin/buddy-vision probe --config config/buddy.json --camera front
```

Run the service:

```sh
.venv/bin/buddy-vision daemon --config config/buddy.json
```

## Offline tools

```sh
buddy-vision replay --config config/buddy.json --camera front --input recording.mp4
buddy-vision compare --config config/buddy.json --camera front --input recording.mp4
buddy-vision benchmark --config config/buddy.json --camera front --input recording.mp4
buddy-vision validate-calibration --config config/buddy.json --camera front
```

Recordings must match the configured resolution. Replay converts decoded BGR
frames to packed YUYV before invoking the same detector boundary.

## Important buffer behavior

Live GStreamer capture yields a packed `uint8` NumPy array with shape
`(height, width, 2)`. The pybind11 layer validates the exact strides and passes
that pointer directly to Team 766's detector while retaining the Python object
and releasing the GIL. This removes a Python-to-C++ copy. The detector's
required host-to-device CUDA transfer still occurs.

## Hardware validation still required

The CUDA module and camera pipeline cannot be executed on a non-CUDA Mac.
Before robot use, run the imported GPU tests, a live known-tag/no-tag probe,
MJPEG/YUYV comparisons, reconnect tests, a 30-minute thermal run, and the
two-camera fairness test on the target Orin.
