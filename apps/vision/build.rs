use std::path::Path;

fn main() {
    println!("cargo:rerun-if-changed=cpp");
    let apriltag = Path::new("cpp/apriltag");
    let mut sources = vec![
        apriltag.join("apriltag.c"),
        apriltag.join("apriltag_quad_thresh.c"),
        apriltag.join("tag36h11.c"),
    ];
    for entry in std::fs::read_dir(apriltag.join("common")).unwrap() {
        let path = entry.unwrap().path();
        let name = path.file_name().unwrap().to_string_lossy();
        // macOS archives can carry AppleDouble `._*.c` sidecars.
        if name.ends_with(".c") && !name.starts_with("._") {
            sources.push(path);
        }
    }
    let mut build = cc::Build::new();
    build
        .files(&sources)
        .include(apriltag)
        .include(apriltag.join("common"))
        // The vendored library predates C23, which newer GCC defaults to.
        .std("gnu11")
        .define("NDEBUG", None)
        .opt_level(3)
        .warnings(false);
    if std::env::var_os("CARGO_FEATURE_JETSON").is_none() {
        build.file("cpp/shim/cpu_detector.c").include("cpp/shim");
    }
    charuco();
    if std::env::var_os("CARGO_FEATURE_JETSON").is_some() {
        jetson();
    }
    // Static libraries resolve in link order; the detectors above use this one.
    build.compile("apriltag");
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

/// NVJPG decoding (Jetson Multimedia API) and the CUDA detector.
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

    team766();
}

/// The Team 766 / FRC 971 CUDA detector, built on the vendored umich AprilTag library.
fn team766() {
    let sources = [
        "apriltag_detect",
        "apriltag_gpu",
        "cuda_frc971",
        "labeling_allegretti_2019_BKE",
        "line_fit_filter",
        "points",
        "threshold",
    ];
    cc::Build::new()
        .cuda(true)
        .cudart("shared")
        // Debug info would add -G, which disables device code optimization.
        .debug(false)
        .flag("-arch=sm_87")
        .flag("-rdc=true")
        .flag("-std=c++20")
        .flag("--expt-relaxed-constexpr")
        .flag("--extended-lambda")
        // glog's CMake package normally defines this.
        .define("GLOG_USE_GLOG_EXPORT", None)
        .define("GLOG_USE_GFLAGS", None)
        .files(sources.map(|name| format!("cpp/team766/{name}.cu")))
        .file("cpp/shim/team766_detector.cu")
        .include("cpp/team766")
        .include("cpp/apriltag")
        .include("cpp/apriltag/common")
        .include("cpp/shim")
        .warnings(false)
        .compile("spot_detector");
    for library in ["glog", "gflags", "stdc++"] {
        println!("cargo:rustc-link-lib=dylib={library}");
    }
}
