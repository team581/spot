# Live alpha tag regression images

These four full-resolution grayscale JPEGs were read from the running Jetson's
shared `/api/camera/<id>/frame.jpg` previews on 2026-10-04 at approximately
23:32 UTC. No separate process opened a camera. Camera 1 is 640×480; cameras
2–4 are 1280×720. Each image contains the physical printed Tag 4, also reported
by the running detector. Both native CPU and CUDA detectors independently
detected Tag 4 in subsequent captures from the same stationary setup, with
maximum corresponding-corner differences below 0.01 px.

These images lock down real image decoding, packed YUYV conversion, tag identity,
corner ordering, native detection, repeatability, and no-tag/reset behavior.
The images have **no measured camera/robot pose ground truth** and do not
establish absolute physical pose accuracy. The synthetic corpus in
`../regression/` supplies independent geometry ground truth.

JPEGs are already in the corrected preview orientation. Do not rotate them a
second time. Replace or add fixtures intentionally; do not refresh them from
hardware during the offline test suite.
