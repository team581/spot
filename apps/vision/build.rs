use std::path::Path;

fn main() {
    println!("cargo:rerun-if-changed=cpp");
    charuco();
    if std::env::var_os("CARGO_FEATURE_JETSON").is_some() {
        jetson();
    }
}

/// ChArUco detection and calibration through OpenCV, found with pkg-config.
fn charuco() {
    let opencv =
        pkg_config::Config::new().cargo_metadata(false).probe("opencv4").unwrap_or_else(|e| {
            panic!("OpenCV 4 not found ({e}); install it or build inside `nix develop`")
        });
    let mut build = cc::Build::new();
    build.cpp(true).std("c++17").file("cpp/shim/charuco.cpp").warnings(false);
    for path in &opencv.include_paths {
        build.include(path);
    }
    build.compile("spot_charuco");
    for path in &opencv.link_paths {
        println!("cargo:rustc-link-search=native={}", path.display());
    }
    for library in
        ["opencv_objdetect", "opencv_calib3d", "opencv_imgcodecs", "opencv_imgproc", "opencv_core"]
    {
        println!("cargo:rustc-link-lib=dylib={library}");
    }
}

fn env(name: &str) -> String {
    println!("cargo:rerun-if-env-changed={name}");
    std::env::var(name).unwrap_or_else(|_| panic!("{name} must be set for Jetson builds"))
}

/// NVJPG decoding (Jetson Multimedia API) and the detector's GPU stage.
fn jetson() {
    let api = env("SPOT_JETSON_MULTIMEDIA_API");
    let classes = Path::new(&api).join("samples/common/classes");
    cc::Build::new()
        .cpp(true)
        .std("c++17")
        .file("cpp/shim/nvjpg.cpp")
        .files(
            [
                "NvJpegDecoder",
                "NvElement",
                "NvElementProfiler",
                "NvLogging",
                "NvBuffer",
                "NvBufSurface",
            ]
            .map(|name| classes.join(format!("{name}.cpp"))),
        )
        .include(Path::new(&api).join("include"))
        .include(Path::new(&api).join("include/libjpeg-9f"))
        .warnings(false)
        .compile("spot_nvjpg");
    for dir in env("SPOT_NVJPG_LIBRARY_DIRS").split(':') {
        println!("cargo:rustc-link-search=native={dir}");
    }
    for library in ["nvmm_jpeg", "nvbufsurface", "nvbufsurftransform", "cuda"] {
        println!("cargo:rustc-link-lib=dylib={library}");
    }

    dense();
}

/// The tag detector's dense stage.
fn dense() {
    cc::Build::new()
        .cuda(true)
        .cudart("shared")
        // Debug info would add -G, which disables device code optimization.
        .debug(false)
        .flag("-arch=sm_87")
        .flag("-std=c++17")
        .file("cpp/shim/dense.cu")
        .warnings(false)
        .compile("spot_dense");
}
