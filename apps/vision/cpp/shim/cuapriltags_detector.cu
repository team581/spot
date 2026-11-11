// tag36h11 detection with NVIDIA's libcuapriltags (from Isaac ROS), behind detector.h.
#include <cuda_runtime.h>

#include <cstdio>
#include <new>

#include "cuAprilTags.h"
#include "detector.h"

struct spot_detector {
  cuAprilTagsHandle handle;
  cudaStream_t stream;
  uint8_t *gray;
  uchar3 *rgb;
  int32_t width, height;
};

namespace {

__global__ void GrayToRgb(const uint8_t *gray, uchar3 *rgb, int count) {
  const int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < count) rgb[i] = make_uchar3(gray[i], gray[i], gray[i]);
}

bool Fail(cudaError_t status, const char *what, char *error, int32_t len) {
  if (status == cudaSuccess) return false;
  std::snprintf(error, len, "%s: %s", what, cudaGetErrorString(status));
  return true;
}

}  // namespace

extern "C" spot_detector *spot_detector_new(int32_t width, int32_t height, char *error,
                                            int32_t len) {
  auto *self = new (std::nothrow) spot_detector{};
  if (self == nullptr) return nullptr;
  self->width = width;
  self->height = height;
  const size_t pixels = static_cast<size_t>(width) * height;
  if (Fail(cudaStreamCreate(&self->stream), "stream", error, len) ||
      Fail(cudaMalloc(&self->gray, pixels), "gray buffer", error, len) ||
      Fail(cudaMalloc(&self->rgb, pixels * sizeof(uchar3)), "RGB buffer", error, len)) {
    spot_detector_free(self);
    return nullptr;
  }
  // Intrinsics only affect the library's own pose output, which Spot does not use.
  const cuAprilTagsCameraIntrinsics_t intrinsics{1.0f, 1.0f, width / 2.0f, height / 2.0f};
  if (const int status = nvCreateAprilTagsDetector(&self->handle, width, height, 4,
                                                   NVAT_TAG36H11, &intrinsics, 1.0f)) {
    std::snprintf(error, len, "nvCreateAprilTagsDetector failed (%d)", status);
    self->handle = nullptr;
    spot_detector_free(self);
    return nullptr;
  }
  return self;
}

extern "C" int32_t spot_detector_detect(spot_detector *self, const uint8_t *gray,
                                        spot_detection *out, int32_t capacity, char *error,
                                        int32_t len) {
  const int count = self->width * self->height;
  if (Fail(cudaMemcpyAsync(self->gray, gray, count, cudaMemcpyHostToDevice, self->stream),
           "upload", error, len))
    return -1;
  GrayToRgb<<<(count + 255) / 256, 256, 0, self->stream>>>(self->gray, self->rgb, count);
  if (Fail(cudaGetLastError(), "convert", error, len)) return -1;
  const cuAprilTagsImageInput_t input{self->rgb, self->width * sizeof(uchar3),
                                      static_cast<uint16_t>(self->width),
                                      static_cast<uint16_t>(self->height)};
  cuAprilTagsID_t tags[64];
  uint32_t found = 0;
  const uint32_t max = capacity < 64 ? capacity : 64;
  if (const int status = cuAprilTagsDetect(self->handle, &input, tags, &found, max, self->stream)) {
    std::snprintf(error, len, "cuAprilTagsDetect failed (%d)", status);
    return -1;
  }
  if (Fail(cudaStreamSynchronize(self->stream), "detect", error, len)) return -1;
  for (uint32_t i = 0; i < found; ++i) {
    out[i].id = tags[i].id;
    out[i].hamming = tags[i].hamming_error;
    out[i].decision_margin = 0.0f;
    for (int c = 0; c < 4; ++c) {
      out[i].corners[c][0] = tags[i].corners[c].x;
      out[i].corners[c][1] = tags[i].corners[c].y;
    }
  }
  return static_cast<int32_t>(found);
}

extern "C" void spot_detector_free(spot_detector *self) {
  if (self->handle != nullptr) cuAprilTagsDestroy(self->handle);
  cudaFree(self->gray);
  cudaFree(self->rgb);
  if (self->stream != nullptr) cudaStreamDestroy(self->stream);
  delete self;
}
