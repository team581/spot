// ChArUco detection, board images, and camera calibration through OpenCV.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <new>
#include <vector>

#include <opencv2/calib3d.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/objdetect/charuco_detector.hpp>

struct spot_charuco {
  cv::aruco::CharucoBoard board;
  cv::aruco::CharucoDetector detector;
};

namespace {

void Message(const std::exception &e, char *error, int32_t len) {
  std::snprintf(error, len, "%s", e.what());
}

}  // namespace

// `dictionary` is a cv::aruco::PredefinedDictionaryType value.
extern "C" spot_charuco *spot_charuco_new(int32_t squares_x, int32_t squares_y,
                                          double square_size, double marker_size,
                                          int32_t dictionary, char *error, int32_t len) {
  try {
    cv::aruco::CharucoBoard board(cv::Size(squares_x, squares_y), static_cast<float>(square_size),
                                  static_cast<float>(marker_size),
                                  cv::aruco::getPredefinedDictionary(dictionary));
    cv::aruco::CharucoDetector detector(board);
    return new spot_charuco{board, detector};
  } catch (const std::exception &e) {
    Message(e, error, len);
    return nullptr;
  }
}

extern "C" void spot_charuco_free(spot_charuco *self) { delete self; }

// Writes up to `capacity` interpolated chessboard corners. Returns the count, or -1.
extern "C" int32_t spot_charuco_detect(spot_charuco *self, const uint8_t *gray, int32_t width,
                                       int32_t height, float *corners, int32_t *ids,
                                       int32_t capacity, char *error, int32_t len) {
  try {
    const cv::Mat image(height, width, CV_8UC1, const_cast<uint8_t *>(gray));
    std::vector<cv::Point2f> found;
    std::vector<int> found_ids;
    self->detector.detectBoard(image, found, found_ids);
    const int32_t count = std::min<int32_t>(capacity, static_cast<int32_t>(found.size()));
    for (int32_t i = 0; i < count; ++i) {
      corners[2 * i] = found[i].x;
      corners[2 * i + 1] = found[i].y;
      ids[i] = found_ids[i];
    }
    return count;
  } catch (const std::exception &e) {
    Message(e, error, len);
    return -1;
  }
}

// PNG of the board at `pixels_per_square`. Free `*png` with `spot_charuco_free_buffer`.
extern "C" int32_t spot_charuco_image(spot_charuco *self, int32_t pixels_per_square,
                                      uint8_t **png, size_t *png_len, char *error, int32_t len) {
  try {
    const cv::Size squares = self->board.getChessboardSize();
    cv::Mat image;
    self->board.generateImage(
        cv::Size(squares.width * pixels_per_square, squares.height * pixels_per_square), image);
    std::vector<uint8_t> bytes;
    cv::imencode(".png", image, bytes);
    *png = static_cast<uint8_t *>(std::malloc(bytes.size()));
    std::memcpy(*png, bytes.data(), bytes.size());
    *png_len = bytes.size();
    return 0;
  } catch (const std::exception &e) {
    Message(e, error, len);
    return -1;
  }
}

extern "C" void spot_charuco_free_buffer(uint8_t *buffer) { std::free(buffer); }

// Calibrates from `frames` views; view `f` has `counts[f]` corners, packed in order in
// `ids` and `corners`. Writes the camera matrix (row-major), five distortion
// coefficients, each view's RMS error, and the overall RMS error.
extern "C" int32_t spot_charuco_calibrate(spot_charuco *self, int32_t frames,
                                          const int32_t *counts, const int32_t *ids,
                                          const float *corners, int32_t width, int32_t height,
                                          double *camera, double *distortion,
                                          double *view_errors, double *rms, char *error,
                                          int32_t len) {
  try {
    std::vector<std::vector<cv::Point3f>> object_points;
    std::vector<std::vector<cv::Point2f>> image_points;
    size_t offset = 0;
    for (int32_t f = 0; f < frames; ++f) {
      std::vector<cv::Point2f> view_corners;
      std::vector<int> view_ids;
      for (int32_t i = 0; i < counts[f]; ++i, ++offset) {
        view_corners.emplace_back(corners[2 * offset], corners[2 * offset + 1]);
        view_ids.push_back(ids[offset]);
      }
      cv::Mat objects, images;
      self->board.matchImagePoints(view_corners, view_ids, objects, images);
      object_points.emplace_back(objects.begin<cv::Point3f>(), objects.end<cv::Point3f>());
      image_points.emplace_back(images.begin<cv::Point2f>(), images.end<cv::Point2f>());
    }
    cv::Mat k, d, intrinsic_deviations, extrinsic_deviations, errors;
    std::vector<cv::Mat> rotations, translations;
    *rms = cv::calibrateCamera(object_points, image_points, cv::Size(width, height), k, d,
                               rotations, translations, intrinsic_deviations,
                               extrinsic_deviations, errors);
    for (int i = 0; i < 9; ++i) camera[i] = k.at<double>(i / 3, i % 3);
    for (int i = 0; i < 5; ++i) distortion[i] = d.at<double>(i);
    for (int32_t f = 0; f < frames; ++f) view_errors[f] = errors.at<double>(f);
    return 0;
  } catch (const std::exception &e) {
    Message(e, error, len);
    return -1;
  }
}
