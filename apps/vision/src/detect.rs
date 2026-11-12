//! tag36h11 detection with the detector in `apriltag`. Jetson builds run its dense stage on the
//! GPU, straight from NVJPG output in GPU memory.

use crate::apriltag::{self, ImageView, Lens, Source};
use crate::config::Calibration;
use crate::decode::{Gray, Pixels};

#[derive(Debug, Clone, serde::Serialize)]
pub struct Detection {
    pub id: u32,
    pub hamming: u32,
    pub decision_margin: f32,
    /// Pixel corners, with pixel centres at integer coordinates: bottom-left, bottom-right,
    /// top-right, top-left of an upright tag.
    pub corners: [[f64; 2]; 4],
}

pub struct Detector {
    inner: apriltag::Detector,
    width: u32,
    height: u32,
    calibration: Option<Calibration>,
}

impl Detector {
    /// The calibration, when known, lets the detector fit tag edges in undistorted space.
    pub fn new(width: u32, height: u32, calibration: Option<&Calibration>) -> anyhow::Result<Self> {
        let lens = calibration.map(|k| Lens {
            fx: k.fx as f32,
            fy: k.fy as f32,
            cx: k.cx as f32,
            cy: k.cy as f32,
            distortion: k.distortion.map(|d| d as f32),
        });
        let config = apriltag::Config { lens, ..Default::default() };
        Ok(Self {
            inner: apriltag::Detector::new(width as usize, height as usize, config)?,
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
        let (width, height) = (self.width as usize, self.height as usize);
        let source = match &gray.pixels {
            Pixels::Host(pixels) => Source::Host(
                ImageView::new(pixels, width, height, width)
                    .ok_or_else(|| anyhow::anyhow!("image size mismatch"))?,
            ),
            #[cfg(feature = "jetson")]
            Pixels::Device { ptr, pitch } => Source::Device { ptr: *ptr, pitch: *pitch },
            #[cfg(not(feature = "jetson"))]
            Pixels::Device { .. } => anyhow::bail!("device images need the jetson feature"),
        };
        let tags = self.inner.detect(&source)?;
        Ok(tags
            .into_iter()
            .map(|t| Detection {
                id: t.id,
                hamming: t.hamming,
                decision_margin: t.decision_margin,
                corners: t.corners,
            })
            .collect())
    }

    /// The last detected image's pixels in CPU memory.
    pub fn host_pixels<'a>(&'a self, gray: &'a Gray) -> &'a [u8] {
        match &gray.pixels {
            Pixels::Host(pixels) => pixels,
            #[cfg(feature = "jetson")]
            Pixels::Device { .. } => self.inner.host_pixels(),
            #[cfg(not(feature = "jetson"))]
            Pixels::Device { .. } => unreachable!("only Jetson builds decode to device memory"),
        }
    }
}

#[cfg(test)]
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
            assert!((corner[0] - expected[0]).hypot(corner[1] - expected[1]) < 0.5, "{corner:?}");
        }
    }
}
