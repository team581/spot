cmake_minimum_required(VERSION 3.24)
project(BuddyVision LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BUDDY_BUILD_CUDA "Build the Team 766 CUDA detector" ON)
option(BUDDY_BUILD_CUDA_TESTS "Build upstream CUDA detector tests" OFF)
set(BUDDY_CUDA_ARCHITECTURES "87" CACHE STRING "CUDA architectures (Orin is 87)")

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

if(BUDDY_BUILD_CUDA)
  enable_language(CUDA)
  set(CMAKE_CUDA_STANDARD 20)
  set(CMAKE_CUDA_STANDARD_REQUIRED ON)
  set(CMAKE_CUDA_ARCHITECTURES "${BUDDY_CUDA_ARCHITECTURES}")
  set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} --expt-relaxed-constexpr --extended-lambda")

  find_package(CUDAToolkit REQUIRED)
  find_package(gflags REQUIRED)
  find_package(glog REQUIRED)
  find_package(Threads REQUIRED)
  set(BUDDY_CCCL_ROOT "" CACHE PATH "Optional pre-downloaded NVIDIA CCCL 2.3.2 root")
  if(NOT BUDDY_CCCL_ROOT)
    include(FetchContent)
    FetchContent_Declare(cccl_upstream
      GIT_REPOSITORY https://github.com/NVIDIA/cccl.git
      GIT_TAG 64d3a5f0c1c83ed83be8c0a9a1f0cdb31f913e81
      GIT_SHALLOW TRUE
    )
    FetchContent_GetProperties(cccl_upstream)
    if(NOT cccl_upstream_POPULATED)
      FetchContent_Populate(cccl_upstream)
    endif()
    set(BUDDY_CCCL_ROOT "${cccl_upstream_SOURCE_DIR}")
  endif()
  file(GLOB APRILTAG_COMMON_SOURCES CONFIGURE_DEPENDS cpp/apriltag/common/*.c)
  file(GLOB APRILTAG_FAMILY_SOURCES CONFIGURE_DEPENDS cpp/apriltag/tag*.c)
  # macOS archive tools can materialize AppleDouble metadata as `._*.c` files.
  # Never allow those sidecars to enter a Linux deployment build.
  list(FILTER APRILTAG_COMMON_SOURCES EXCLUDE REGEX "/\\._[^/]+\\.c$")
  list(FILTER APRILTAG_FAMILY_SOURCES EXCLUDE REGEX "/\\._[^/]+\\.c$")
  add_library(apriltag STATIC
    cpp/apriltag/apriltag.c
    cpp/apriltag/apriltag_pose.c
    cpp/apriltag/apriltag_quad_thresh.c
    ${APRILTAG_COMMON_SOURCES}
    ${APRILTAG_FAMILY_SOURCES}
  )
  set_target_properties(apriltag PROPERTIES POSITION_INDEPENDENT_CODE ON)
  target_include_directories(apriltag PUBLIC cpp/apriltag cpp/apriltag/common)
  target_link_libraries(apriltag PUBLIC Threads::Threads ${CMAKE_DL_LIBS})
  if(UNIX AND NOT APPLE)
    target_link_libraries(apriltag PUBLIC m)
  endif()

  set(TEAM766_SOURCES
    cpp/team766/apriltag_detect.cu
    cpp/team766/apriltag_gpu.cu
    cpp/team766/apriltag_utils.cu
    cpp/team766/cuda_frc971.cu
    cpp/team766/labeling_allegretti_2019_BKE.cu
    cpp/team766/line_fit_filter.cu
    cpp/team766/points.cu
    cpp/team766/threshold.cu
  )

  add_library(team766_apriltags_cuda STATIC ${TEAM766_SOURCES})
  set_target_properties(team766_apriltags_cuda PROPERTIES
    CUDA_SEPARABLE_COMPILATION ON
    POSITION_INDEPENDENT_CODE ON
  )
  target_include_directories(team766_apriltags_cuda PUBLIC
    cpp/team766
    ${BUDDY_CCCL_ROOT}/cub
    ${BUDDY_CCCL_ROOT}/thrust
    ${BUDDY_CCCL_ROOT}/libcudacxx/include
  )
  if(TARGET gflags::gflags)
    set(BUDDY_GFLAGS_TARGET gflags::gflags)
  else()
    set(BUDDY_GFLAGS_TARGET gflags)
  endif()
  target_link_libraries(team766_apriltags_cuda PUBLIC
    CUDA::cudart
    apriltag
    ${BUDDY_GFLAGS_TARGET}
    glog::glog
  )

  pybind11_add_module(_buddy_cuda MODULE cpp/bindings.cu)
  target_link_libraries(_buddy_cuda PRIVATE team766_apriltags_cuda)
  install(TARGETS _buddy_cuda LIBRARY DESTINATION buddy_vision)

  if(BUDDY_BUILD_CUDA_TESTS)
    enable_testing()
    find_package(GTest REQUIRED)
    find_package(OpenCV REQUIRED COMPONENTS core imgcodecs imgproc)
    add_executable(gpu_detector_test cpp/tests/gpu_detector_test.cu)
    target_include_directories(gpu_detector_test PRIVATE cpp/team766)
    target_compile_definitions(gpu_detector_test PRIVATE
      BUDDY_TEST_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/data")
    target_link_libraries(gpu_detector_test PRIVATE
      team766_apriltags_cuda GTest::gtest ${OpenCV_LIBS})
    add_test(NAME gpu_detector_test COMMAND gpu_detector_test)
  endif()
else()
  pybind11_add_module(_buddy_cuda MODULE cpp/stub_bindings.cpp)
  install(TARGETS _buddy_cuda LIBRARY DESTINATION buddy_vision)
endif()
