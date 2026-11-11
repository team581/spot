// tag36h11 detection with the Team 766 / FRC 971 CUDA detector, behind detector.h.
#include <cstdio>
#include <exception>
#include <memory>
#include <new>

#include "apriltag_gpu.h"
#include "detector.h"
extern "C" {
#include "apriltag.h"
#include "tag36h11.h"
}

struct spot_detector {
  apriltag_family_t *family;
  apriltag_detector_t *detector;
  std::unique_ptr<frc971::apriltag::GpuDetector> gpu;
};

extern "C" spot_detector *spot_detector_new(int32_t width, int32_t height,
                                            const double *intrinsics, char *error,
                                            int32_t len) {
  if (width % 8 != 0 || height % 8 != 0) {
    std::snprintf(error, len, "image size must be a multiple of 8");
    return nullptr;
  }
  auto *self = new (std::nothrow) spot_detector{};
  if (self == nullptr) return nullptr;
  self->family = tag36h11_create();
  self->detector = apriltag_detector_create();
  apriltag_detector_add_family_bits(self->detector, self->family, 1);
  // The CUDA detector requires 2x decimation.
  self->detector->quad_decimate = 2.0;
  self->detector->quad_sigma = 0.0;
  self->detector->nthreads = 1;
  self->detector->refine_edges = true;
  self->detector->wp = workerpool_create(1);
  try {
    // Edges are fit in undistorted space and corners mapped back to image pixels.
    // Uncalibrated cameras use nominal intrinsics without distortion.
    const double nominal[9] = {1000.0, 1000.0, width / 2.0, height / 2.0, 0, 0, 0, 0, 0};
    const double *k = intrinsics != nullptr ? intrinsics : nominal;
    const frc971::apriltag::CameraMatrix camera{.fx = k[0], .cx = k[2], .fy = k[1], .cy = k[3]};
    const frc971::apriltag::DistCoeffs distortion{
        .k1 = k[4], .k2 = k[5], .p1 = k[6], .p2 = k[7], .k3 = k[8]};
    self->gpu = std::make_unique<frc971::apriltag::GpuDetector>(width, height, self->detector,
                                                                 camera, distortion);
  } catch (const std::exception &e) {
    std::snprintf(error, len, "%s", e.what());
    spot_detector_free(self);
    return nullptr;
  }
  return self;
}

extern "C" int32_t spot_detector_detect(spot_detector *self, const uint8_t *gray, int32_t pitch,
                                        int32_t on_device, spot_detection *out,
                                        int32_t capacity, char *error, int32_t len) {
  (void)error;
  (void)len;
  self->gpu->Detect(gray, pitch, on_device != 0);
  const zarray_t *detections = self->gpu->Detections();
  int32_t count = 0;
  for (int i = 0; i < zarray_size(detections) && count < capacity; ++i) {
    apriltag_detection_t *detection = nullptr;
    zarray_get(detections, i, &detection);
    spot_detection *target = &out[count++];
    target->id = detection->id;
    target->hamming = detection->hamming;
    target->decision_margin = detection->decision_margin;
    for (int c = 0; c < 4; ++c) {
      target->corners[c][0] = detection->p[c][0];
      target->corners[c][1] = detection->p[c][1];
    }
  }
  return count;
}

extern "C" const uint8_t *spot_detector_gray(spot_detector *self) {
  return self->gpu->GrayHost();
}

extern "C" void spot_detector_free(spot_detector *self) {
  self->gpu.reset();
  if (self->detector != nullptr) apriltag_detector_destroy(self->detector);
  if (self->family != nullptr) tag36h11_destroy(self->family);
  delete self;
}
