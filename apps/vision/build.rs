fn main() {
    println!("cargo:rerun-if-changed=cpp");
    charuco();
    if std::env::var_os("CARGO_FEATURE_JETSON").is_some() {
        dense();
    }
}

/// ChArUco detection and calibration through OpenCV, found with pkg-config.
fn charuco() {
    let opencv = pkg_config::Config::new()
        .cargo_metadata(false)
        .atleast_version("5.1")
        .probe("opencv5")
        .unwrap_or_else(|e| panic!("OpenCV 5.1 or newer not found ({e})"));
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
        ["opencv_objdetect", "opencv_calib", "opencv_imgcodecs", "opencv_imgproc", "opencv_core"]
    {
        println!("cargo:rustc-link-lib=dylib={library}");
    }
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
