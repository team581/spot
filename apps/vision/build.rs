use std::path::Path;

fn main() {
    println!("cargo:rerun-if-changed=cpp");
    let apriltag = Path::new("cpp/apriltag");
    let mut sources = vec![
        apriltag.join("apriltag.c"),
        apriltag.join("apriltag_pose.c"),
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
        .define("NDEBUG", None)
        .opt_level(3)
        .warnings(false);
    if std::env::var_os("CARGO_FEATURE_JETSON").is_none() {
        build.file("cpp/shim/cpu_detector.c").include("cpp/shim");
    }
    build.compile("apriltag");
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

/// NVJPG decoding (Jetson Multimedia API) and libcuapriltags detection.
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

    let cuapriltags = env("SPOT_CUAPRILTAGS");
    cc::Build::new()
        .cuda(true)
        .cudart("shared")
        .flag("-arch=sm_87")
        .file("cpp/shim/cuapriltags_detector.cu")
        .include("cpp/shim")
        .include(Path::new(&cuapriltags).join("include"))
        .compile("spot_detector");
    println!("cargo:rustc-link-search=native={cuapriltags}/lib");
    println!("cargo:rustc-link-lib=static=cuapriltags");
    println!("cargo:rustc-link-lib=dylib=stdc++");
}
