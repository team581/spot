// MJPEG decode on the Jetson NVJPG engine, returning the luma plane.

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>

#include "NvJpegDecoder.h"
#include "nvbufsurface.h"

namespace py = pybind11;

namespace {

class NvjpgDecoder {
 public:
  NvjpgDecoder() : decoder_(NvJPEGDecoder::createJPEGDecoder("spot-nvjpg")) {
    if (!decoder_) throw std::runtime_error("NVJPG decoder unavailable");
  }

  py::array_t<std::uint8_t> Decode(const py::buffer &data) {
    const py::buffer_info input = data.request();
    if (input.itemsize != 1 || input.ndim != 1) throw py::value_error("expected JPEG bytes");
    // The decoder only reads its input despite the non-const signature.
    auto *bytes = static_cast<unsigned char *>(input.ptr);
    // Take the lock only while the GIL is released so waiters cannot deadlock.
    std::unique_lock<std::mutex> lock(mutex_, std::defer_lock);
    NvBufSurface *surface = nullptr;
    std::uint32_t width = 0, height = 0;
    {
      py::gil_scoped_release release;
      lock.lock();
      int fd = -1;
      std::uint32_t format = 0;
      if (decoder_->decodeToFd(fd, bytes, input.size, format, width, height) < 0)
        throw std::runtime_error("NVJPG could not decode the frame");
      if (NvBufSurfaceFromFd(fd, reinterpret_cast<void **>(&surface)) < 0 ||
          NvBufSurfaceMap(surface, 0, 0, NVBUF_MAP_READ) < 0)
        throw std::runtime_error("NVJPG output could not be mapped");
      NvBufSurfaceSyncForCpu(surface, 0, 0);
    }
    py::array_t<std::uint8_t> luma({height, width});
    auto *target = luma.mutable_data();
    {
      py::gil_scoped_release release;
      // The mapping is uncached, so copy whole rows rather than individual pixels.
      const auto &plane = surface->surfaceList[0];
      const auto *source = static_cast<const std::uint8_t *>(plane.mappedAddr.addr[0]);
      for (std::uint32_t row = 0; row < height; ++row)
        std::memcpy(target + static_cast<std::size_t>(row) * width,
                    source + static_cast<std::size_t>(row) * plane.planeParams.pitch[0], width);
      NvBufSurfaceUnMap(surface, 0, 0);
    }
    return luma;
  }

 private:
  std::unique_ptr<NvJPEGDecoder> decoder_;
  std::mutex mutex_;
};

}  // namespace

PYBIND11_MODULE(_spot_nvjpg, module) {
  py::class_<NvjpgDecoder>(module, "NvjpgDecoder")
      .def(py::init<>())
      .def("decode", &NvjpgDecoder::Decode, py::arg("data"));
}
