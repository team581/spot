// MJPEG decode on the Jetson NVJPG engine into memory CUDA kernels read directly.
#include <cuda.h>
#include <cudaEGL.h>
#include <cuda_runtime.h>

#include <cstdint>
#include <cstdio>
#include <new>

#include "NvJpegDecoder.h"
#include "nvbufsurface.h"

struct spot_nvjpg {
  NvJPEGDecoder *decoder;
  // NVJPG reuses its output buffer, so it is registered with CUDA once.
  int registered_fd = -1;
  CUgraphicsResource resource = nullptr;
};

extern "C" spot_nvjpg *spot_nvjpg_new() {
  // Make the CUDA runtime's context current on this thread for the driver calls below.
  if (cudaFree(nullptr) != cudaSuccess) return nullptr;
  NvJPEGDecoder *decoder = NvJPEGDecoder::createJPEGDecoder("spot-nvjpg");
  if (decoder == nullptr) return nullptr;
  return new (std::nothrow) spot_nvjpg{decoder};
}

// Decodes to a luma plane in device memory, valid until the next decode.
extern "C" int32_t spot_nvjpg_decode(spot_nvjpg *self, const uint8_t *jpeg, size_t len,
                                     const uint8_t **luma, uint32_t *pitch, uint32_t *width,
                                     uint32_t *height, char *error, int32_t error_len) {
  int fd = -1;
  uint32_t format = 0;
  // The decoder only reads its input despite the non-const signature.
  if (self->decoder->decodeToFd(fd, const_cast<uint8_t *>(jpeg), len, format, *width, *height) <
      0) {
    std::snprintf(error, error_len, "could not decode the frame");
    return -1;
  }
  if (fd != self->registered_fd) {
    if (self->resource != nullptr) cuGraphicsUnregisterResource(self->resource);
    self->resource = nullptr;
    self->registered_fd = -1;
    NvBufSurface *surface = nullptr;
    if (NvBufSurfaceFromFd(fd, reinterpret_cast<void **>(&surface)) < 0 ||
        NvBufSurfaceMapEglImage(surface, 0) < 0 ||
        cuGraphicsEGLRegisterImage(&self->resource, surface->surfaceList[0].mappedAddr.eglImage,
                                   CU_GRAPHICS_MAP_RESOURCE_FLAGS_NONE) != CUDA_SUCCESS) {
      std::snprintf(error, error_len, "output could not be mapped for CUDA");
      return -1;
    }
    self->registered_fd = fd;
  }
  CUeglFrame frame;
  if (cuGraphicsResourceGetMappedEglFrame(&frame, self->resource, 0, 0) != CUDA_SUCCESS) {
    std::snprintf(error, error_len, "output could not be mapped for CUDA");
    return -1;
  }
  *luma = static_cast<const uint8_t *>(frame.frame.pPitch[0]);
  *pitch = frame.pitch;
  return 0;
}

extern "C" void spot_nvjpg_free(spot_nvjpg *self) {
  if (self->resource != nullptr) cuGraphicsUnregisterResource(self->resource);
  delete self->decoder;
  delete self;
}
