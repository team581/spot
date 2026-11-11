// C interface shared by Spot's detector backends.
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct spot_detection {
  int32_t id;
  int32_t hamming;
  float decision_margin;
  // Image corners in the umich AprilTag order: (-1, 1), (1, 1), (1, -1), (-1, -1) in tag
  // coordinates, which is bottom-left, bottom-right, top-right, top-left for an upright tag.
  double corners[4][2];
} spot_detection;

typedef struct spot_detector spot_detector;

// `intrinsics` is fx, fy, cx, cy, k1, k2, p1, p2, k3 (OpenCV's model), or NULL when the
// camera is uncalibrated. Returns NULL and fills `error` on failure.
spot_detector *spot_detector_new(int32_t width, int32_t height, const double *intrinsics,
                                 char *error, int32_t error_len);
// Detects tag36h11 tags in an 8-bit grayscale image of the detector's size, with rows
// `pitch` bytes apart, in CUDA device memory when `on_device` is nonzero.
// Returns the number of detections written (at most `capacity`), or -1 and fills `error`.
int32_t spot_detector_detect(spot_detector *detector, const uint8_t *gray, int32_t pitch,
                             int32_t on_device, spot_detection *out, int32_t capacity,
                             char *error, int32_t error_len);
// The last detected image as packed host memory, or NULL if the caller already has it.
const uint8_t *spot_detector_gray(spot_detector *detector);
void spot_detector_free(spot_detector *detector);

#ifdef __cplusplus
}
#endif
