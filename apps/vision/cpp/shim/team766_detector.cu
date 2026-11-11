// tag36h11 quad candidates from the Team 766 / FRC 971 CUDA detector, decoded in Rust.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <memory>
#include <new>
#include <vector>

#include "apriltag_gpu.h"
#include "camera_geometry.h"

using frc971::apriltag::GpuDetector;

extern "C" {

struct spot_quad {
  // Corners in image pixels, wound like umich AprilTag's quads.
  float corners[4][2];
  int32_t reversed_border;
};

}  // extern "C"

struct spot_detector {
  int32_t width, height;
  frc971::apriltag::CameraMatrix camera;
  frc971::apriltag::DistCoeffs distortion;
  std::unique_ptr<GpuDetector> gpu;
  std::vector<spot_quad> quads;
};

// `intrinsics` is fx, fy, cx, cy, k1, k2, p1, p2, k3 (OpenCV's model), or NULL when the
// camera is uncalibrated. Returns NULL and fills `error` on failure.
extern "C" spot_detector *spot_detector_new(int32_t width, int32_t height,
                                            const double *intrinsics, char *error,
                                            int32_t len) {
  if (width % 8 != 0 || height % 8 != 0) {
    std::snprintf(error, len, "image size must be a multiple of 8");
    return nullptr;
  }
  // Edges are fit in undistorted space and corners mapped back to image pixels.
  // Uncalibrated cameras use nominal intrinsics without distortion.
  const double nominal[9] = {1000.0, 1000.0, width / 2.0, height / 2.0, 0, 0, 0, 0, 0};
  const double *k = intrinsics != nullptr ? intrinsics : nominal;
  auto *self = new (std::nothrow) spot_detector{
      .width = width,
      .height = height,
      .camera = {.fx = k[0], .cx = k[2], .fy = k[1], .cy = k[3]},
      .distortion = {.k1 = k[4], .k2 = k[5], .p1 = k[6], .p2 = k[7], .k3 = k[8]},
  };
  if (self == nullptr) return nullptr;
  try {
    self->gpu = std::make_unique<GpuDetector>(width, height);
  } catch (const std::exception &e) {
    std::snprintf(error, len, "%s", e.what());
    delete self;
    return nullptr;
  }
  return self;
}

// Finds quad candidates in an 8-bit grayscale image of the detector's size, with rows
// `pitch` bytes apart, in CUDA device memory when `on_device` is nonzero. Points `quads`
// at the candidates, valid until the next detection, and returns how many there are.
extern "C" int32_t spot_detector_detect(spot_detector *self, const uint8_t *gray,
                                        int32_t pitch, int32_t on_device,
                                        const spot_quad **quads) {
  self->gpu->Detect(gray, pitch, on_device != 0);
  self->quads.clear();
  for (const auto &corners : self->gpu->Quads()) {
    spot_quad quad;
    std::memcpy(quad.corners, corners.corners, sizeof(quad.corners));
    quad.reversed_border = corners.reversed_border;
    // Search as far as decimation could have misplaced an edge.
    frc971::apriltag::RefineEdges(self->gpu->GrayHost(), self->width, self->height,
                                  GpuDetector::kQuadDecimate + 1, quad.corners,
                                  corners.reversed_border, &self->camera, &self->distortion);
    self->quads.push_back(quad);
  }
  *quads = self->quads.data();
  return static_cast<int32_t>(self->quads.size());
}

// The last detected image as packed host memory.
extern "C" const uint8_t *spot_detector_gray(spot_detector *self) {
  return self->gpu->GrayHost();
}

extern "C" void spot_detector_free(spot_detector *self) { delete self; }
