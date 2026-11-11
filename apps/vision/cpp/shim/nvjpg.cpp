// MJPEG decode on the Jetson NVJPG engine, returning the luma plane.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <new>

#include "NvJpegDecoder.h"
#include "nvbufsurface.h"

struct spot_nvjpg {
  NvJPEGDecoder *decoder;
};

extern "C" spot_nvjpg *spot_nvjpg_new() {
  NvJPEGDecoder *decoder = NvJPEGDecoder::createJPEGDecoder("spot-nvjpg");
  if (decoder == nullptr) return nullptr;
  return new (std::nothrow) spot_nvjpg{decoder};
}

extern "C" int32_t spot_nvjpg_decode(spot_nvjpg *self, const uint8_t *jpeg, size_t len,
                                     uint8_t *out, size_t capacity, uint32_t *width,
                                     uint32_t *height, char *error, int32_t error_len) {
  int fd = -1;
  uint32_t format = 0;
  // The decoder only reads its input despite the non-const signature.
  if (self->decoder->decodeToFd(fd, const_cast<uint8_t *>(jpeg), len, format, *width, *height) <
      0) {
    std::snprintf(error, error_len, "could not decode the frame");
    return -1;
  }
  if (static_cast<size_t>(*width) * *height > capacity) {
    std::snprintf(error, error_len, "frame is larger than its header");
    return -1;
  }
  NvBufSurface *surface = nullptr;
  if (NvBufSurfaceFromFd(fd, reinterpret_cast<void **>(&surface)) < 0 ||
      NvBufSurfaceMap(surface, 0, 0, NVBUF_MAP_READ) < 0) {
    std::snprintf(error, error_len, "output could not be mapped");
    return -1;
  }
  NvBufSurfaceSyncForCpu(surface, 0, 0);
  // The mapping is uncached, so copy whole rows rather than individual pixels.
  const auto &plane = surface->surfaceList[0];
  const auto *source = static_cast<const uint8_t *>(plane.mappedAddr.addr[0]);
  for (uint32_t row = 0; row < *height; ++row)
    std::memcpy(out + static_cast<size_t>(row) * *width,
                source + static_cast<size_t>(row) * plane.planeParams.pitch[0], *width);
  NvBufSurfaceUnMap(surface, 0, 0);
  return 0;
}

extern "C" void spot_nvjpg_free(spot_nvjpg *self) {
  delete self->decoder;
  delete self;
}
