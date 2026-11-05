// gpu_detector_test.cpp
#include <glog/logging.h>
#include <gtest/gtest.h>

#include "apriltag_gpu.h"
#include "apriltag_utils.h"
#include "line_fit_filter.h"
#include "opencv2/opencv.hpp"

extern "C" {
#include "apriltag.h"
}

using namespace cv;

// Fixture for the GpuDetector tests
class GpuDetectorTest : public ::testing::Test {
 protected:
  Mat yuyv_img, bgr_img, yuyv_img_notags, bgr_img_notags;

  apriltag_family_t *tf = nullptr;
  apriltag_detector_t *td = nullptr;
  const char *tag_family = "tag36h11";
  frc971::apriltag::CameraMatrix cam;
  frc971::apriltag::DistCoeffs dist;

  void SetUp() override {
    // Read in the image
    bgr_img = cv::imread(SPOT_TEST_DATA_DIR "/colorimage.jpg", cv::IMREAD_COLOR);
    cvtColor(bgr_img, yuyv_img, COLOR_BGR2YUV_YUYV);

    bgr_img_notags =
        cv::imread(SPOT_TEST_DATA_DIR "/colorimage_notags.jpg", cv::IMREAD_COLOR);
    cvtColor(bgr_img_notags, yuyv_img_notags, COLOR_BGR2YUV_YUYV);

    // Setup Tag Family and tag detector
    setup_tag_family(&tf, tag_family);
    td = apriltag_detector_create();
    apriltag_detector_add_family(td, tf);

    // Setup Tag Detector
    td->quad_decimate = 2.0;
    td->quad_sigma = 0.0;
    td->nthreads = 1;
    td->debug = false;
    td->refine_edges = true;
    td->wp = workerpool_create(1);

    // Setup Camera Matrix
    cam.fx = 905.495617;
    cam.fy = 907.909470;
    cam.cx = 609.916016;
    cam.cy = 352.682645;

    // Setup Distortion Coefficients
    dist.k1 = 0.059238;
    dist.k2 = -0.075154;
    dist.p1 = -0.003801;
    dist.p2 = 0.001113;
    dist.k3 = 0.0;
  }

  void TearDown() override {
    // Cleanup code here if needed
    apriltag_detector_destroy(td);
    teardown_tag_family(&tf, tag_family);
  }
};

// Test to ensure GpuDetector detects an AprilTag correctly
TEST_F(GpuDetectorTest, GpuDetectsAprilTag) {
  int width = yuyv_img.cols;
  int height = yuyv_img.rows;
  frc971::apriltag::GpuDetector detector(width, height, td, cam, dist);
  detector.Detect(yuyv_img.data);
  const zarray_t *detections = detector.Detections();

  ASSERT_EQ(1, zarray_size(detections));
}

TEST_F(GpuDetectorTest, GpuNoAprilTagDetections) {
  int width = yuyv_img_notags.cols;
  int height = yuyv_img_notags.rows;
  frc971::apriltag::GpuDetector detector(width, height, td, cam, dist);
  detector.Detect(yuyv_img_notags.data);
  const zarray_t *detections = detector.Detections();

  ASSERT_EQ(0, zarray_size(detections));
}

TEST(GpuLaunchTest, EmptyFitsDoNotLaunchKernels) {
  frc971::apriltag::CudaStream stream;
  ASSERT_EQ(cudaSuccess, cudaGetLastError());
  frc971::apriltag::FitLines(nullptr, 0, nullptr, 0, nullptr, nullptr, nullptr,
                            &stream);
  ASSERT_EQ(cudaSuccess, cudaGetLastError());
  frc971::apriltag::FitQuads(nullptr, 0, nullptr, 0, nullptr, 10, nullptr, 0, 0,
                            nullptr, &stream);
  ASSERT_EQ(cudaSuccess, cudaGetLastError());
  ASSERT_EQ(cudaSuccess, cudaStreamSynchronize(stream.get()));
}

TEST_F(GpuDetectorTest, BlankFramesDoNotPoisonFollowingTagFrames) {
  Mat blank(yuyv_img.rows, yuyv_img.cols, CV_8UC2, Scalar(0, 128));
  frc971::apriltag::GpuDetector detector(yuyv_img.cols, yuyv_img.rows, td, cam,
                                        dist);
  for (int repeat = 0; repeat < 2; ++repeat) {
    detector.Detect(blank.data);
    ASSERT_EQ(0, zarray_size(detector.Detections()));
    ASSERT_EQ(cudaSuccess, cudaGetLastError());
    detector.Detect(yuyv_img.data);
    ASSERT_EQ(1, zarray_size(detector.Detections()));
    ASSERT_EQ(cudaSuccess, cudaGetLastError());
  }
}

TEST_F(GpuDetectorTest, CpuDetectsAprilTag) {
  Mat gray;
  cvtColor(bgr_img, gray, COLOR_BGR2GRAY);
  image_u8_t im = {gray.cols, gray.rows, gray.cols, gray.data};
  zarray_t *detections = apriltag_detector_detect(td, &im);

  ASSERT_EQ(1, zarray_size(detections));
}

TEST_F(GpuDetectorTest, CpuNoAprilTagDetections) {
  Mat gray;
  cvtColor(bgr_img_notags, gray, COLOR_BGR2GRAY);
  image_u8_t im = {gray.cols, gray.rows, gray.cols, gray.data};
  zarray_t *detections = apriltag_detector_detect(td, &im);

  ASSERT_EQ(0, zarray_size(detections));
}

TEST_F(GpuDetectorTest, CpuAndGpuEqual) {
  // CPU Detection
  Mat gray;
  cvtColor(bgr_img, gray, COLOR_BGR2GRAY);
  image_u8_t im = {gray.cols, gray.rows, gray.cols, gray.data};
  zarray_t *cpu_detections = apriltag_detector_detect(td, &im);

  ASSERT_EQ(1, zarray_size(cpu_detections));

  // GPU Detection
  int width = yuyv_img.cols;
  int height = yuyv_img.rows;
  frc971::apriltag::GpuDetector detector(width, height, td, cam, dist);
  detector.Detect(yuyv_img.data);
  const zarray_t *gpu_detections = detector.Detections();

  ASSERT_EQ(1, zarray_size(gpu_detections));

  for (int i = 0; i < zarray_size(cpu_detections); i++) {
    apriltag_detection_t *gpudet;
    zarray_get(gpu_detections, i, &gpudet);

    apriltag_detection_t *cpudet;
    zarray_get(cpu_detections, i, &cpudet);

    ASSERT_EQ(cpudet->id, gpudet->id);
    ASSERT_NEAR(cpudet->c[0], gpudet->c[0], 0.5);
    ASSERT_NEAR(cpudet->c[1], gpudet->c[1], 0.5);

    for (int row = 0; row < 4; row++) {
      for (int col = 0; col < 2; col++) {
        ASSERT_NEAR(cpudet->p[row][col], gpudet->p[row][col], 0.5);
      }
    }
  }
}

// Main function to run the tests
int main(int argc, char **argv) {
  ::testing::InitGoogleTest(&argc, argv);
  google::InitGoogleLogging(argv[0]);
  return RUN_ALL_TESTS();
}
