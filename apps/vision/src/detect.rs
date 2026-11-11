//! tag36h11 detection through the C shim in `cpp/shim`.

use std::ffi::{CStr, c_char};

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
    fn spot_detector_new(width: i32, height: i32, error: *mut c_char, len: i32)
    -> *mut RawDetector;
    fn spot_detector_detect(
        detector: *mut RawDetector,
        gray: *const u8,
        out: *mut RawDetection,
        capacity: i32,
        error: *mut c_char,
        len: i32,
    ) -> i32;
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
}

// SAFETY: a detector is only used by one thread at a time.
unsafe impl Send for Detector {}

const CAPACITY: usize = 64;

fn message(buffer: &[c_char]) -> String {
    // SAFETY: the shim always NUL-terminates within the buffer, which starts zeroed.
    unsafe { CStr::from_ptr(buffer.as_ptr()) }.to_string_lossy().into_owned()
}

impl Detector {
    pub fn new(width: u32, height: u32) -> anyhow::Result<Self> {
        let mut error = [0 as c_char; 256];
        // SAFETY: the error buffer outlives the call and its length is passed.
        let raw =
            unsafe { spot_detector_new(width as i32, height as i32, error.as_mut_ptr(), 255) };
        anyhow::ensure!(!raw.is_null(), "detector: {}", message(&error));
        Ok(Self { raw, width, height })
    }

    pub fn size(&self) -> (u32, u32) {
        (self.width, self.height)
    }

    /// Detects tags in a packed grayscale image of the detector's size.
    pub fn detect(&mut self, gray: &[u8]) -> anyhow::Result<Vec<Detection>> {
        anyhow::ensure!(gray.len() == (self.width * self.height) as usize, "image size mismatch");
        let mut out =
            [RawDetection { id: 0, hamming: 0, decision_margin: 0.0, corners: [[0.0; 2]; 4] };
                CAPACITY];
        let mut error = [0 as c_char; 256];
        // SAFETY: `gray` has the detector's dimensions; `out` and `error` have the given capacities.
        let count = unsafe {
            spot_detector_detect(
                self.raw,
                gray.as_ptr(),
                out.as_mut_ptr(),
                CAPACITY as i32,
                error.as_mut_ptr(),
                255,
            )
        };
        anyhow::ensure!(count >= 0, "detector: {}", message(&error));
        #[cfg_attr(not(feature = "jetson"), allow(unused_mut))]
        let mut out = out[..count as usize].to_vec();
        // libcuapriltags reports whole-pixel corners.
        #[cfg(feature = "jetson")]
        self.refine(gray, &mut out)?;
        Ok(out
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
    #[cfg(feature = "jetson")]
    fn refine(&self, gray: &[u8], detections: &mut [RawDetection]) -> anyhow::Result<()> {
        unsafe extern "C" {
            fn spot_refine_corners(
                gray: *const u8,
                width: i32,
                height: i32,
                corners: *mut f32,
                count: i32,
                error: *mut c_char,
                len: i32,
            ) -> i32;
        }
        if detections.is_empty() {
            return Ok(());
        }
        let mut corners: Vec<f32> =
            detections.iter().flat_map(|d| d.corners.iter().flatten().map(|v| *v as f32)).collect();
        let mut error = [0 as c_char; 256];
        // SAFETY: `gray` has the detector's size and `corners` holds `4 * len` points.
        let status = unsafe {
            spot_refine_corners(
                gray.as_ptr(),
                self.width as i32,
                self.height as i32,
                corners.as_mut_ptr(),
                (corners.len() / 2) as i32,
                error.as_mut_ptr(),
                255,
            )
        };
        anyhow::ensure!(status == 0, "corner refinement: {}", message(&error));
        for (detection, points) in detections.iter_mut().zip(corners.chunks(8)) {
            for (corner, point) in detection.corners.iter_mut().zip(points.chunks(2)) {
                *corner = [point[0] as f64, point[1] as f64];
            }
        }
        Ok(())
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
        let detections = Detector::new(width, height).unwrap().detect(&pixels).unwrap();
        assert_eq!(detections.len(), 1);
        let expected = [[587.43, 452.55], [692.32, 452.43], [692.22, 347.76], [587.53, 347.64]];
        for (corner, expected) in detections[0].corners.iter().zip(expected) {
            assert!((corner[0] - expected[0]).hypot(corner[1] - expected[1]) < 1.0, "{corner:?}");
        }
    }
}
