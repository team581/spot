//! tag36h11 detection through the C shim in `cpp/shim`.

use std::ffi::{CStr, c_char};

use crate::config::Calibration;
use crate::decode::{Gray, Pixels};

#[repr(C)]
#[derive(Clone, Copy)]
struct RawDetection {
    id: i32,
    hamming: i32,
    decision_margin: f32,
    corners: [[f64; 2]; 4],
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
        out: *mut RawDetection,
        capacity: i32,
        error: *mut c_char,
        len: i32,
    ) -> i32;
    fn spot_detector_gray(detector: *mut RawDetector) -> *const u8;
    fn spot_detector_free(detector: *mut RawDetector);
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Detection {
    pub id: u32,
    pub hamming: u32,
    pub decision_margin: f32,
    /// Pixel corners: bottom-left, bottom-right, top-right, top-left of an upright tag.
    pub corners: [[f64; 2]; 4],
}

pub struct Detector {
    raw: *mut RawDetector,
    width: u32,
    height: u32,
    calibration: Option<Calibration>,
}

// SAFETY: a detector is only used by one thread at a time.
unsafe impl Send for Detector {}

const CAPACITY: usize = 64;

fn message(buffer: &[c_char]) -> String {
    // SAFETY: the shim always NUL-terminates within the buffer, which starts zeroed.
    unsafe { CStr::from_ptr(buffer.as_ptr()) }.to_string_lossy().into_owned()
}

impl Detector {
    /// The calibration, when known, lets the CUDA detector fit tag edges in undistorted space.
    pub fn new(width: u32, height: u32, calibration: Option<&Calibration>) -> anyhow::Result<Self> {
        let intrinsics = calibration.map(|k| {
            let [k1, k2, p1, p2, k3] = k.distortion;
            [k.fx, k.fy, k.cx, k.cy, k1, k2, p1, p2, k3]
        });
        let mut error = [0 as c_char; 256];
        // SAFETY: the intrinsics and error buffer outlive the call; the error length is passed.
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
        Ok(Self { raw, width, height, calibration: calibration.cloned() })
    }

    /// Whether this detector was made for the given image size and calibration.
    pub fn matches(&self, size: (u32, u32), calibration: Option<&Calibration>) -> bool {
        (self.width, self.height) == size && self.calibration.as_ref() == calibration
    }

    /// Detects tags in a packed grayscale image of the detector's size.
    pub fn detect(&mut self, gray: &Gray) -> anyhow::Result<Vec<Detection>> {
        anyhow::ensure!(
            (gray.width, gray.height) == (self.width, self.height),
            "image size mismatch"
        );
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
        let mut out =
            [RawDetection { id: 0, hamming: 0, decision_margin: 0.0, corners: [[0.0; 2]; 4] };
                CAPACITY];
        let mut error = [0 as c_char; 256];
        // SAFETY: the image has the detector's dimensions and pitch; `out` and `error` have
        // the given capacities.
        let count = unsafe {
            spot_detector_detect(
                self.raw,
                pointer,
                pitch as i32,
                on_device as i32,
                out.as_mut_ptr(),
                CAPACITY as i32,
                error.as_mut_ptr(),
                255,
            )
        };
        anyhow::ensure!(count >= 0, "detector: {}", message(&error));
        Ok(out[..count as usize]
            .iter()
            .map(|d| Detection {
                id: d.id as u32,
                hamming: d.hamming as u32,
                decision_margin: d.decision_margin,
                corners: d.corners,
            })
            .collect())
    }
}

impl Detector {
    /// The last detected image's pixels in CPU memory.
    pub fn host_pixels<'a>(&'a self, gray: &'a Gray) -> &'a [u8] {
        match &gray.pixels {
            Pixels::Host(pixels) => pixels,
            // SAFETY: the detector copies each image to host memory, which stays valid until
            // its next detection; `self` is borrowed for as long as the slice.
            Pixels::Device { .. } => unsafe {
                std::slice::from_raw_parts(
                    spot_detector_gray(self.raw),
                    (self.width * self.height) as usize,
                )
            },
        }
    }
}

impl Drop for Detector {
    fn drop(&mut self) {
        // SAFETY: `raw` came from `spot_detector_new` and is freed once.
        unsafe { spot_detector_free(self.raw) }
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
        let (pixels, width, height) = gray("center.png");
        let gray = Gray { pixels: Pixels::Host(pixels), width, height };
        let detections = Detector::new(width, height, None).unwrap().detect(&gray).unwrap();
        assert_eq!(detections.len(), 1);
        let expected = [[587.43, 452.55], [692.32, 452.43], [692.22, 347.76], [587.53, 347.64]];
        for (corner, expected) in detections[0].corners.iter().zip(expected) {
            assert!((corner[0] - expected[0]).hypot(corner[1] - expected[1]) < 1.0, "{corner:?}");
        }
    }
}
