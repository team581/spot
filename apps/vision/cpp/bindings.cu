#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef SPOT_WITH_CUDA
#include "apriltag_gpu.h"
#endif
#include "camera_geometry.h"
extern "C" {
#include "apriltag.h"
#ifdef SPOT_WITH_CUDA
#include "tag36h11.h"
#endif
}

namespace py = pybind11;
using Clock = std::chrono::steady_clock;

namespace {

struct CameraMatrix {
  double fx = 1.0;
  double fy = 1.0;
  double cx = 0.0;
  double cy = 0.0;
};

struct DistortionCoefficients {
  double k1 = 0.0;
  double k2 = 0.0;
  double p1 = 0.0;
  double p2 = 0.0;
  double k3 = 0.0;
};

#ifdef SPOT_WITH_CUDA
struct DetectorOptions {
  int max_hamming = 2;
};

struct Detection {
  int id = -1;
  int hamming = 0;
  double decision_margin = 0.0;
  std::vector<std::array<double, 2>> corners;
};

struct DetectionBatch {
  std::vector<Detection> detections;
  double detect_ms = 0.0;
  std::uintptr_t input_address = 0;
};

struct DetectorMetrics {
  std::uint64_t calls = 0;
  double last_detect_ms = 0.0;
  double total_detect_ms = 0.0;
  std::uintptr_t last_input_address = 0;
};

#endif

struct FrameView {
  const std::uint8_t *data;
  std::uintptr_t address;
};

FrameView ValidateFrame(const py::array &frame, int width, int height) {
  if (!py::isinstance<py::array_t<std::uint8_t>>(frame)) {
    throw py::type_error("frame must have dtype uint8");
  }
  const py::buffer_info info = frame.request();
  if (info.ndim != 3 || info.shape[0] != height || info.shape[1] != width ||
      info.shape[2] != 2) {
    throw py::value_error("frame must have shape (height, width, 2)");
  }
  if (info.strides[2] != 1 || info.strides[1] != 2 ||
      info.strides[0] != static_cast<py::ssize_t>(width * 2)) {
    throw py::value_error("frame must be packed, C-contiguous YUYV");
  }
  auto *data = static_cast<const std::uint8_t *>(info.ptr);
  return {.data = data, .address = reinterpret_cast<std::uintptr_t>(data)};
}

#ifdef SPOT_WITH_CUDA
Detection ConvertDetection(const apriltag_detection_t &source) {
  Detection result;
  result.id = source.id;
  result.hamming = source.hamming;
  result.decision_margin = source.decision_margin;
  result.corners.reserve(4);
  for (int index = 0; index < 4; ++index) {
    result.corners.push_back({source.p[index][0], source.p[index][1]});
  }
  return result;
}

class DetectorState {
 public:
  explicit DetectorState(const DetectorOptions &options) : options_(options) {
    family_ = tag36h11_create();
    detector_ = apriltag_detector_create();
    if (detector_ == nullptr) throw std::runtime_error("failed to create AprilTag detector");
    apriltag_detector_add_family_bits(detector_, family_, options_.max_hamming);
    // The CUDA detector requires 2x decimation; the remaining values are fixed for Spot.
    detector_->quad_decimate = 2.0;
    detector_->quad_sigma = 0.0;
    detector_->nthreads = 1;
    detector_->refine_edges = true;
    detector_->wp = workerpool_create(1);
  }

  virtual ~DetectorState() {
    if (detector_ != nullptr) apriltag_detector_destroy(detector_);
    if (family_ != nullptr) tag36h11_destroy(family_);
  }

  DetectorState(const DetectorState &) = delete;
  DetectorState &operator=(const DetectorState &) = delete;

  DetectorMetrics Metrics() const {
    std::scoped_lock lock(mutex_);
    return metrics_;
  }

 protected:
  DetectionBatch FinishBatch(const zarray_t *detections, double detect_ms,
                             std::uintptr_t address) {
    DetectionBatch batch;
    batch.detect_ms = detect_ms;
    batch.input_address = address;
    if (detections != nullptr) {
      batch.detections.reserve(zarray_size(detections));
      for (int index = 0; index < zarray_size(detections); ++index) {
        apriltag_detection_t *detection = nullptr;
        zarray_get(detections, index, &detection);
        if (detection != nullptr) batch.detections.push_back(ConvertDetection(*detection));
      }
    }
    ++metrics_.calls;
    metrics_.last_detect_ms = detect_ms;
    metrics_.total_detect_ms += detect_ms;
    metrics_.last_input_address = address;
    return batch;
  }

  DetectorOptions options_;
  apriltag_family_t *family_ = nullptr;
  apriltag_detector_t *detector_ = nullptr;
  mutable std::mutex mutex_;
  DetectorMetrics metrics_;
};

class CudaDetector final : public DetectorState {
 public:
  CudaDetector(int width, int height, const CameraMatrix &camera,
               const DistortionCoefficients &distortion, const DetectorOptions &options)
      : DetectorState(options), width_(width), height_(height) {
    if (width <= 0 || height <= 0 || width % 8 != 0 || height % 8 != 0) {
      throw py::value_error("CUDA detector dimensions must be positive multiples of 8");
    }
    int device_count = 0;
    const cudaError_t device_status = cudaGetDeviceCount(&device_count);
    if (device_status != cudaSuccess || device_count < 1) {
      throw std::runtime_error(std::string("no usable CUDA device: ") +
                               cudaGetErrorString(device_status));
    }
    frc971::apriltag::CameraMatrix native_camera{
        .fx = camera.fx, .cx = camera.cx, .fy = camera.fy, .cy = camera.cy};
    frc971::apriltag::DistCoeffs native_distortion{
        .k1 = distortion.k1, .k2 = distortion.k2, .p1 = distortion.p1,
        .p2 = distortion.p2, .k3 = distortion.k3};
    gpu_detector_ = std::make_unique<frc971::apriltag::GpuDetector>(
        width_, height_, detector_, native_camera, native_distortion);
  }

  DetectionBatch Detect(const py::array &frame) {
    const FrameView view = ValidateFrame(frame, width_, height_);
    std::scoped_lock lock(mutex_);
    const auto start = Clock::now();
    {
      py::gil_scoped_release release;
      gpu_detector_->Detect(view.data);
    }
    const double elapsed = std::chrono::duration<double, std::milli>(Clock::now() - start).count();
    return FinishBatch(gpu_detector_->Detections(), elapsed, view.address);
  }

  void Reset() {
    std::scoped_lock lock(mutex_);
    gpu_detector_->ReinitializeDetections();
    metrics_ = {};
  }

 private:
  int width_;
  int height_;
  std::unique_ptr<frc971::apriltag::GpuDetector> gpu_detector_;
};

#endif

}  // namespace

PYBIND11_MODULE(_spot_cuda, module) {
  module.doc() = "Team 766 CUDA AprilTag detector bindings for Spot Vision";
#ifdef SPOT_WITH_CUDA
  module.attr("CUDA_AVAILABLE") = true;
#else
  module.attr("CUDA_AVAILABLE") = false;
#endif

  module.def("undistort_points", [](const std::vector<std::array<double, 2>> &points,
                                     const CameraMatrix &camera,
                                     const DistortionCoefficients &distortion) {
    frc971::apriltag::CameraMatrix k{camera.fx, camera.cx, camera.fy, camera.cy};
    frc971::apriltag::DistCoeffs d{distortion.k1, distortion.k2, distortion.p1,
                                distortion.p2, distortion.k3};
    auto result = points;
    for (auto &point : result) {
      if (!frc971::apriltag::UnDistort(&point[0], &point[1], &k, &d))
        throw py::value_error("point undistortion did not converge");
    }
    return result;
  });
  module.def("refine_corners", [](const py::array &frame,
                                   const std::array<std::array<float, 2>, 4> &corners,
                                   const CameraMatrix &camera,
                                   const DistortionCoefficients &distortion,
                                   double decimate) {
    const auto info = frame.request();
    if (info.ndim != 3) throw py::value_error("expected packed YUYV frame");
    const int height = info.shape[0], width = info.shape[1];
    const auto view = ValidateFrame(frame, width, height);
    std::vector<std::uint8_t> gray(width * height);
    for (size_t i = 0; i < gray.size(); ++i) gray[i] = view.data[i * 2];
    image_u8_t image{width, height, width, gray.data()};
    struct quad q{};
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 2; ++j) q.p[i][j] = corners[i][j];
    apriltag_detector_t detector{};
    detector.quad_decimate = decimate;
    frc971::apriltag::CameraMatrix k{camera.fx, camera.cx, camera.fy, camera.cy};
    frc971::apriltag::DistCoeffs d{distortion.k1, distortion.k2, distortion.p1,
                                distortion.p2, distortion.k3};
    frc971::apriltag::RefineEdges(&detector, &image, &q, &k, &d);
    std::array<std::array<float, 2>, 4> result{};
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 2; ++j) result[i][j] = q.p[i][j];
    return result;
  }, py::arg("frame"), py::arg("corners"), py::arg("camera"),
     py::arg("distortion"), py::arg("decimate") = 2.0);

  py::class_<CameraMatrix>(module, "CameraMatrix")
      .def(py::init<>()).def_readwrite("fx", &CameraMatrix::fx)
      .def_readwrite("fy", &CameraMatrix::fy).def_readwrite("cx", &CameraMatrix::cx)
      .def_readwrite("cy", &CameraMatrix::cy);
  py::class_<DistortionCoefficients>(module, "DistortionCoefficients")
      .def(py::init<>()).def_readwrite("k1", &DistortionCoefficients::k1)
      .def_readwrite("k2", &DistortionCoefficients::k2)
      .def_readwrite("p1", &DistortionCoefficients::p1)
      .def_readwrite("p2", &DistortionCoefficients::p2)
      .def_readwrite("k3", &DistortionCoefficients::k3);
#ifdef SPOT_WITH_CUDA
  py::class_<DetectorOptions>(module, "DetectorOptions")
      .def(py::init<>()).def_readwrite("max_hamming", &DetectorOptions::max_hamming);
  py::class_<Detection>(module, "Detection")
      .def_readonly("id", &Detection::id).def_readonly("hamming", &Detection::hamming)
      .def_readonly("decision_margin", &Detection::decision_margin)
      .def_readonly("corners", &Detection::corners);
  py::class_<DetectionBatch>(module, "DetectionBatch")
      .def_readonly("detections", &DetectionBatch::detections)
      .def_readonly("detect_ms", &DetectionBatch::detect_ms)
      .def_readonly("input_address", &DetectionBatch::input_address);
  py::class_<DetectorMetrics>(module, "DetectorMetrics")
      .def_readonly("calls", &DetectorMetrics::calls)
      .def_readonly("last_detect_ms", &DetectorMetrics::last_detect_ms)
      .def_readonly("total_detect_ms", &DetectorMetrics::total_detect_ms)
      .def_readonly("last_input_address", &DetectorMetrics::last_input_address);
  py::class_<CudaDetector>(module, "CudaDetector")
      .def(py::init<int, int, const CameraMatrix &, const DistortionCoefficients &,
                    const DetectorOptions &>())
      .def("detect", &CudaDetector::Detect).def("metrics", &CudaDetector::Metrics)
      .def("reset", &CudaDetector::Reset);
#endif
}
