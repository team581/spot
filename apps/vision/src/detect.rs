//! tag36h11 detection with kornia-apriltag. Jetson builds find quads with the CUDA detector in
//! `cpp/shim` and decode them here.

use std::sync::Arc;

use kornia_apriltag::decoder::Detection as Decoded;
use kornia_apriltag::family::TagFamily;
use kornia_image::{Image, ImageSize};

use crate::config::Calibration;
use crate::decode::{Gray, Pixels};

#[derive(Debug, Clone, serde::Serialize)]
pub struct Detection {
    pub id: u32,
    pub hamming: u32,
    pub decision_margin: f32,
    /// Pixel corners: bottom-left, bottom-right, top-right, top-left of an upright tag.
    pub corners: [[f64; 2]; 4],
}

impl From<&Decoded> for Detection {
    fn from(decoded: &Decoded) -> Self {
        // Tag coordinates of the corners above; y points down the upright tag.
        let corners = [(-1.0, 1.0), (1.0, 1.0), (1.0, -1.0), (-1.0, -1.0)].map(|(x, y)| {
            let p = decoded.quad.homography_project(x, y);
            [f64::from(p.x), f64::from(p.y)]
        });
        Self {
            id: decoded.id.into(),
            hamming: decoded.hamming.into(),
            decision_margin: decoded.decision_margin,
            corners,
        }
    }
}

fn tag36h11() -> TagFamily {
    // Correcting more bit errors trades false positives for range.
    TagFamily::tag36_h11().and_then(|f| f.with_max_hamming(1)).expect("tag36h11 is valid")
}

/// Runs `f` on packed host pixels without copying them.
fn with_image<R>(
    pixels: &[u8],
    width: u32,
    height: u32,
    f: impl FnOnce(&Image<u8, 1>) -> R,
) -> anyhow::Result<R> {
    let size = ImageSize { width: width as usize, height: height as usize };
    anyhow::ensure!(pixels.len() == size.width * size.height, "image size mismatch");
    // SAFETY: `pixels` covers the whole image and outlives the image, which `f` only borrows.
    let image = unsafe { Image::from_borrowed_host_readonly(size, pixels.as_ptr(), Arc::new(()))? };
    Ok(f(&image))
}

fn sorted(decoded: &[Decoded]) -> Vec<Detection> {
    let mut detections: Vec<Detection> = decoded.iter().map(Detection::from).collect();
    detections.sort_by_key(|d| d.id);
    detections
}

pub struct Detector {
    backend: backend::Backend,
    width: u32,
    height: u32,
    calibration: Option<Calibration>,
}

impl Detector {
    /// The calibration, when known, lets the CUDA detector fit tag edges in undistorted space.
    pub fn new(width: u32, height: u32, calibration: Option<&Calibration>) -> anyhow::Result<Self> {
        Ok(Self {
            backend: backend::Backend::new(width, height, calibration)?,
            width,
            height,
            calibration: calibration.cloned(),
        })
    }

    /// Whether this detector was made for the given image size and calibration.
    pub fn matches(&self, size: (u32, u32), calibration: Option<&Calibration>) -> bool {
        (self.width, self.height) == size && self.calibration.as_ref() == calibration
    }

    /// Detects tags in a grayscale image of the detector's size.
    pub fn detect(&mut self, gray: &Gray) -> anyhow::Result<Vec<Detection>> {
        anyhow::ensure!(
            (gray.width, gray.height) == (self.width, self.height),
            "image size mismatch"
        );
        self.backend.detect(gray)
    }

    /// The last detected image's pixels in CPU memory.
    pub fn host_pixels<'a>(&'a self, gray: &'a Gray) -> &'a [u8] {
        match &gray.pixels {
            Pixels::Host(pixels) => pixels,
            Pixels::Device { .. } => self.backend.host_pixels(),
        }
    }
}

#[cfg(not(feature = "jetson"))]
mod backend {
    use kornia_apriltag::family::TagFamilyKind;
    use kornia_apriltag::{AprilTagDecoder, DecodeTagsConfig};

    use super::*;

    pub struct Backend {
        decoder: AprilTagDecoder,
    }

    impl Backend {
        pub fn new(width: u32, height: u32, _: Option<&Calibration>) -> anyhow::Result<Self> {
            let mut config = DecodeTagsConfig::new(vec![TagFamilyKind::from(tag36h11())])?;
            // The classic midpoint, as the CUDA detector thresholds.
            config.threshold_split = 0.5;
            let size = ImageSize { width: width as usize, height: height as usize };
            Ok(Self { decoder: AprilTagDecoder::new(config, size)? })
        }

        pub fn detect(&mut self, gray: &Gray) -> anyhow::Result<Vec<Detection>> {
            let Pixels::Host(pixels) = &gray.pixels else {
                anyhow::bail!("the CPU detector needs host memory");
            };
            let decoded =
                with_image(pixels, gray.width, gray.height, |image| self.decoder.decode(image))??;
            Ok(sorted(&decoded))
        }

        pub fn host_pixels(&self) -> &[u8] {
            unreachable!("CPU images are always in host memory")
        }
    }
}

#[cfg(feature = "jetson")]
mod backend {
    use std::ffi::{CStr, c_char};

    use kornia_apriltag::decoder::{decode_tags, dedup_detections};
    use kornia_apriltag::family::TagFamilyKind;
    use kornia_apriltag::quad::Quad;

    use super::*;

    #[repr(C)]
    struct RawQuad {
        corners: [[f32; 2]; 4],
        reversed_border: i32,
    }

    #[repr(C)]
    struct RawDetector {
        _private: [u8; 0],
    }

    unsafe extern "C" {
        fn spot_detector_new(
            width: i32,
            height: i32,
            intrinsics: *const f64,
            error: *mut c_char,
            len: i32,
        ) -> *mut RawDetector;
        fn spot_detector_detect(
            detector: *mut RawDetector,
            gray: *const u8,
            pitch: i32,
            on_device: i32,
            quads: *mut *const RawQuad,
        ) -> i32;
        fn spot_detector_gray(detector: *mut RawDetector) -> *const u8;
        fn spot_detector_free(detector: *mut RawDetector);
    }

    fn message(buffer: &[c_char]) -> String {
        // SAFETY: the shim always NUL-terminates within the buffer, which starts zeroed.
        unsafe { CStr::from_ptr(buffer.as_ptr()) }.to_string_lossy().into_owned()
    }

    pub struct Backend {
        raw: *mut RawDetector,
        families: Vec<(TagFamilyKind, TagFamily)>,
        width: u32,
        height: u32,
    }

    // SAFETY: a detector is only used by one thread at a time.
    unsafe impl Send for Backend {}

    impl Backend {
        pub fn new(
            width: u32,
            height: u32,
            calibration: Option<&Calibration>,
        ) -> anyhow::Result<Self> {
            let intrinsics = calibration.map(|k| {
                let [k1, k2, p1, p2, k3] = k.distortion;
                [k.fx, k.fy, k.cx, k.cy, k1, k2, p1, p2, k3]
            });
            let mut error = [0 as c_char; 256];
            // SAFETY: the intrinsics and error buffer outlive the call; the error length is
            // passed.
            let raw = unsafe {
                spot_detector_new(
                    width as i32,
                    height as i32,
                    intrinsics.as_ref().map_or(std::ptr::null(), |k| k.as_ptr()),
                    error.as_mut_ptr(),
                    255,
                )
            };
            anyhow::ensure!(!raw.is_null(), "detector: {}", message(&error));
            Ok(Self { raw, families: vec![(TagFamilyKind::Tag36H11, tag36h11())], width, height })
        }

        pub fn detect(&mut self, gray: &Gray) -> anyhow::Result<Vec<Detection>> {
            let (pointer, pitch, on_device) = match &gray.pixels {
                Pixels::Host(pixels) => {
                    anyhow::ensure!(
                        pixels.len() == (self.width * self.height) as usize,
                        "image size mismatch"
                    );
                    (pixels.as_ptr(), self.width as usize, false)
                }
                Pixels::Device { ptr, pitch } => (*ptr, *pitch, true),
            };
            let mut raw_quads = std::ptr::null();
            // SAFETY: the image has the detector's dimensions and pitch.
            let count = unsafe {
                spot_detector_detect(
                    self.raw,
                    pointer,
                    pitch as i32,
                    on_device as i32,
                    &mut raw_quads,
                )
            };
            let raw_quads = match count {
                0 => &[][..],
                // SAFETY: the shim returns `count` quads that stay valid until its next
                // detection, which needs `&mut self`.
                _ => unsafe { std::slice::from_raw_parts(raw_quads, count as usize) },
            };
            // Edges were already refined in undistorted space.
            let mut quads: Vec<Quad> = raw_quads
                .iter()
                .map(|q| Quad {
                    corners: q.corners.map(|[x, y]| kornia_algebra::Vec2F32::new(x, y)),
                    reversed_border: q.reversed_border != 0,
                    ..Default::default()
                })
                .collect();
            let pixels = match &gray.pixels {
                Pixels::Host(pixels) => pixels.as_slice(),
                Pixels::Device { .. } => self.host_pixels(),
            };
            let decoded = with_image(pixels, self.width, self.height, |image| {
                // umich AprilTag's default sharpening.
                decode_tags(image, &mut quads, &self.families, false, 0.25, 0.0)
            })?;
            Ok(sorted(&dedup_detections(decoded)))
        }

        pub fn host_pixels(&self) -> &[u8] {
            // SAFETY: the detector copies each image to host memory, which stays valid until
            // its next detection; `self` is borrowed for as long as the slice.
            unsafe {
                std::slice::from_raw_parts(
                    spot_detector_gray(self.raw),
                    (self.width * self.height) as usize,
                )
            }
        }
    }

    impl Drop for Backend {
        fn drop(&mut self) {
            // SAFETY: `raw` came from `spot_detector_new` and is freed once.
            unsafe { spot_detector_free(self.raw) }
        }
    }
}

#[cfg(all(test, not(feature = "jetson")))]
mod tests {
    use super::*;

    fn gray(name: &str) -> (Vec<u8>, u32, u32) {
        let path = format!("{}/tests/data/regression/{name}", env!("CARGO_MANIFEST_DIR"));
        let image = image::open(path).unwrap().to_luma8();
        let (width, height) = image.dimensions();
        (image.into_raw(), width, height)
    }

    #[test]
    fn detects_corners_in_order() {
        let (pixels, width, height) = gray("center.jpg");
        let gray = Gray { pixels: Pixels::Host(pixels), width, height };
        let detections = Detector::new(width, height, None).unwrap().detect(&gray).unwrap();
        assert_eq!(detections.len(), 1);
        let expected = [[587.43, 452.55], [692.32, 452.43], [692.22, 347.76], [587.53, 347.64]];
        for (corner, expected) in detections[0].corners.iter().zip(expected) {
            assert!((corner[0] - expected[0]).hypot(corner[1] - expected[1]) < 1.0, "{corner:?}");
        }
    }
}
