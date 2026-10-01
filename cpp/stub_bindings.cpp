#include <pybind11/pybind11.h>

namespace py = pybind11;

PYBIND11_MODULE(_spot_cuda, module) {
  module.doc() = "Spot Vision placeholder built without CUDA";
  module.attr("CUDA_AVAILABLE") = false;
}
