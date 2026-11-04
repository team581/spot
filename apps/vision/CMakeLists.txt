cmake_minimum_required(VERSION 3.24)
project(SpotVision LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(SPOT_BUILD_CUDA "Build the Team 766 CUDA detector" OFF)
option(SPOT_BUILD_CUDA_TESTS "Build upstream CUDA detector tests" OFF)
set(SPOT_CUDA_ARCHITECTURES "87" CACHE STRING "CUDA architectures (Orin is 87)")

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

# These vendored source sets only change when the project is reconfigured.
# CONFIGURE_DEPENDS loops indefinitely when the Jetson checkout is reached
# through its compatibility symlink and Ninja compares the two paths.
file(GLOB APRILTAG_COMMON_SOURCES cpp/apriltag/common/*.c)
file(GLOB APRILTAG_FAMILY_SOURCES cpp/apriltag/tag*.c)
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
find_package(Threads REQUIRED)
target_link_libraries(apriltag PUBLIC Threads::Threads ${CMAKE_DL_LIBS})
if(UNIX AND NOT APPLE)
  target_link_libraries(apriltag PUBLIC m)
endif()

# Both schemas accompany every installed artifact. v1 remains an alpha client
# compatibility contract; production robot integration uses the distinct v2.
install(FILES proto/vision.proto proto/vision_v2.proto proto/README.md
  DESTINATION spot_vision/schemas)


if(SPOT_BUILD_CUDA)
  # CMake probes the default architecture while enabling CUDA, so configure
  # Orin's architecture before compiler detection rather than afterward.
  if(NOT CMAKE_CUDA_ARCHITECTURES)
    set(CMAKE_CUDA_ARCHITECTURES "${SPOT_CUDA_ARCHITECTURES}")
  endif()
  enable_language(CUDA)
  set(CMAKE_CUDA_STANDARD 20)
  set(CMAKE_CUDA_STANDARD_REQUIRED ON)
  set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} --expt-relaxed-constexpr --extended-lambda")

  find_package(CUDAToolkit REQUIRED)
  find_package(gflags REQUIRED)
  find_package(glog REQUIRED)
  find_package(Threads REQUIRED)
  set(SPOT_CCCL_ROOT "" CACHE PATH "Optional pre-downloaded NVIDIA CCCL 2.3.2 root")
  if(NOT SPOT_CCCL_ROOT)
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
    set(SPOT_CCCL_ROOT "${cccl_upstream_SOURCE_DIR}")
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
    ${SPOT_CCCL_ROOT}/cub
    ${SPOT_CCCL_ROOT}/thrust
    ${SPOT_CCCL_ROOT}/libcudacxx/include
  )
  if(TARGET gflags::gflags)
    set(SPOT_GFLAGS_TARGET gflags::gflags)
  else()
    set(SPOT_GFLAGS_TARGET gflags)
  endif()
  target_link_libraries(team766_apriltags_cuda PUBLIC
    CUDA::cudart
    apriltag
    ${SPOT_GFLAGS_TARGET}
    glog::glog
  )

  pybind11_add_module(_spot_cuda MODULE cpp/bindings.cu)
  target_compile_definitions(_spot_cuda PRIVATE SPOT_WITH_CUDA=1)
  target_link_libraries(_spot_cuda PRIVATE team766_apriltags_cuda)
  install(TARGETS _spot_cuda LIBRARY DESTINATION spot_vision)

  if(SPOT_BUILD_CUDA_TESTS)
    enable_testing()
    find_package(GTest REQUIRED)
    find_package(OpenCV REQUIRED COMPONENTS core imgcodecs imgproc)
    add_executable(gpu_detector_test cpp/tests/gpu_detector_test.cu)
    target_include_directories(gpu_detector_test PRIVATE cpp/team766)
    target_compile_definitions(gpu_detector_test PRIVATE
      SPOT_TEST_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/data")
    target_link_libraries(gpu_detector_test PRIVATE
      team766_apriltags_cuda GTest::gtest ${OpenCV_LIBS})
    add_test(NAME gpu_detector_test COMMAND gpu_detector_test)
  endif()
else()
  pybind11_add_module(_spot_cuda MODULE cpp/host_bindings.cpp cpp/host_apriltag_utils.cpp)
  target_include_directories(_spot_cuda PRIVATE cpp/team766)
  target_link_libraries(_spot_cuda PRIVATE apriltag)
  install(TARGETS _spot_cuda LIBRARY DESTINATION spot_vision)
endif()

# Hash the exact module loaded by the installed Python process. Build identity
# stays in the build directory and is never inferred from a runtime checkout.
get_filename_component(SPOT_REPOSITORY_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(SPOT_DOCS_DIR "${SPOT_REPOSITORY_ROOT}/dist/jetson-docs" CACHE PATH "Prebuilt Starlight site for /docs/")
if(NOT EXISTS "${SPOT_DOCS_DIR}/index.html" OR NOT EXISTS "${SPOT_DOCS_DIR}/pagefind/pagefind.js")
  message(FATAL_ERROR "Build the bundled documentation first: pnpm --filter spot-docs build:jetson")
endif()
# The dashboard is a pnpm workspace, but only its flat runtime assets are bundled.
file(GLOB SPOT_WEB_ASSETS LIST_DIRECTORIES false
  "${CMAKE_CURRENT_SOURCE_DIR}/../dashboard/*")
list(APPEND SPOT_WEB_ASSETS "${SPOT_REPOSITORY_ROOT}/packages/camera-viewer/viewer.js")
list(FILTER SPOT_WEB_ASSETS EXCLUDE REGEX "/package\\.json$")
add_custom_target(spot_build_manifest ALL
  COMMAND "${CMAKE_COMMAND}" -E rm -rf "${CMAKE_CURRENT_BINARY_DIR}/web"
  COMMAND "${CMAKE_COMMAND}" -E make_directory "${CMAKE_CURRENT_BINARY_DIR}/web"
  COMMAND "${CMAKE_COMMAND}" -E copy
    ${SPOT_WEB_ASSETS} "${CMAKE_CURRENT_BINARY_DIR}/web"
  COMMAND "${CMAKE_COMMAND}" -E touch "${CMAKE_CURRENT_BINARY_DIR}/web/__init__.py"
  COMMAND "${CMAKE_COMMAND}" -E copy_directory
    "${SPOT_DOCS_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/web/docs"
  COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/build_manifest.py"
    --root "${SPOT_REPOSITORY_ROOT}" --native "$<TARGET_FILE:_spot_cuda>"
    --cuda "${SPOT_BUILD_CUDA}" --web-assets "${CMAKE_CURRENT_BINARY_DIR}/web" --output "${CMAKE_CURRENT_BINARY_DIR}/build-manifest.json"
  DEPENDS _spot_cuda
  VERBATIM)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/build-manifest.json" DESTINATION spot_vision)

# Install one matching bundle rather than updated HTML with missing screenshots
# or an older stylesheet. Normalize permissions for the service account.
install(DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/web/" DESTINATION spot_vision/web
  FILE_PERMISSIONS OWNER_READ OWNER_WRITE GROUP_READ WORLD_READ
  DIRECTORY_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE)
