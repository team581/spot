{
  lib,
  stdenv,
  fetchFromGitHub,
  cmake,
  ninja,
  pkg-config,
  libpng,
  zlib,
}:
stdenv.mkDerivation (finalAttrs: {
  # The pinned Nixpkgs still packages OpenCV 4.
  pname = "opencv";
  version = "5.1.0";
  src = fetchFromGitHub {
    owner = "opencv";
    repo = "opencv";
    tag = finalAttrs.version;
    hash = "sha256-36KmbxhKCerIrpItFGyQL7duGKS9AQB75+cGqSI/y74=";
  };
  nativeBuildInputs = [
    cmake
    ninja
    pkg-config
  ];
  buildInputs = [
    libpng
    zlib
  ];
  cmakeFlags = [
    # OpenCV prefixes these paths when generating opencv5.pc.
    (lib.cmakeFeature "CMAKE_INSTALL_LIBDIR" "lib")
    (lib.cmakeFeature "CMAKE_INSTALL_INCLUDEDIR" "include")
    (lib.cmakeFeature "BUILD_LIST" "calib,imgcodecs,objdetect")
    (lib.cmakeBool "OPENCV_GENERATE_PKGCONFIG" true)
    (lib.cmakeBool "BUILD_TESTS" false)
    (lib.cmakeBool "BUILD_PERF_TESTS" false)
    (lib.cmakeBool "BUILD_EXAMPLES" false)
    (lib.cmakeBool "BUILD_opencv_apps" false)
    (lib.cmakeBool "BUILD_PNG" false)
    (lib.cmakeBool "BUILD_ZLIB" false)
    (lib.cmakeBool "WITH_IPP" false)
    (lib.cmakeBool "WITH_KLEIDICV" false)
    (lib.cmakeBool "WITH_OPENEXR" false)
    (lib.cmakeBool "WITH_OPENJPEG" false)
    (lib.cmakeBool "WITH_JPEG" false)
    (lib.cmakeBool "WITH_TIFF" false)
    (lib.cmakeBool "WITH_WEBP" false)
  ];
  meta.license = lib.licenses.asl20;
})
