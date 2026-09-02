#include <pybind11/pybind11.h>

namespace py = pybind11;

PYBIND11_MODULE(_buddy_cuda, module) {
  module.doc() = "Buddy Vision placeholder built without CUDA";
  module.attr("CUDA_AVAILABLE") = false;
}
