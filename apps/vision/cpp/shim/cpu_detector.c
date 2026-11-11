// CPU tag36h11 detector for development machines, using the vendored umich AprilTag library.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "apriltag.h"
#include "detector.h"
#include "tag36h11.h"

struct spot_detector {
  apriltag_detector_t *detector;
  apriltag_family_t *family;
  int32_t width, height;
};

spot_detector *spot_detector_new(int32_t width, int32_t height, const double *intrinsics,
                                 char *error, int32_t error_len) {
  (void)intrinsics;
  (void)error;
  (void)error_len;
  spot_detector *result = calloc(1, sizeof(*result));
  result->family = tag36h11_create();
  result->detector = apriltag_detector_create();
  apriltag_detector_add_family_bits(result->detector, result->family, 1);
  result->detector->quad_decimate = 2.0f;
  result->detector->nthreads = 2;
  result->detector->refine_edges = true;
  result->width = width;
  result->height = height;
  return result;
}

int32_t spot_detector_detect(spot_detector *detector, const uint8_t *gray, int32_t pitch,
                             int32_t on_device, spot_detection *out, int32_t capacity,
                             char *error, int32_t error_len) {
  if (on_device) {
    snprintf(error, error_len, "the CPU detector needs host memory");
    return -1;
  }
  image_u8_t image = {detector->width, detector->height, pitch, (uint8_t *)gray};
  zarray_t *detections = apriltag_detector_detect(detector->detector, &image);
  int32_t count = 0;
  for (int i = 0; i < zarray_size(detections) && count < capacity; ++i) {
    apriltag_detection_t *detection;
    zarray_get(detections, i, &detection);
    spot_detection *target = &out[count++];
    target->id = detection->id;
    target->hamming = detection->hamming;
    target->decision_margin = detection->decision_margin;
    memcpy(target->corners, detection->p, sizeof(target->corners));
  }
  apriltag_detections_destroy(detections);
  return count;
}

const uint8_t *spot_detector_gray(spot_detector *detector) {
  (void)detector;
  return NULL;
}

void spot_detector_free(spot_detector *detector) {
  apriltag_detector_destroy(detector->detector);
  tag36h11_destroy(detector->family);
  free(detector);
}
