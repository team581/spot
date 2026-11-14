//! One camera's frame processing: a JPEG in; tags, a pose estimate, and a ChArUco view out.
//! Jetson builds decode on the NVJPG engine and run the detector's dense stage on the GPU,
//! straight from NVJPG output in GPU memory.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use nalgebra::Isometry3;

use crate::apriltag::{self, ImageView, Lens, Source, Tag};
use crate::calibration::{Charuco, View};
use crate::config::{Calibration, CameraConfig, FieldLayout, RobotConfig};
use crate::decode::{Decoder, Pixels};
use crate::pose::{self, Estimate, TagObservation};

/// How to process a camera's frames.
pub struct Processing {
    pub calibration: Option<Calibration>,
    pub mount: Isometry3<f64>,
    pub tag_size: f64,
    pub ignored_tags: Vec<u32>,
    pub layout: Option<Arc<FieldLayout>>,
    /// Detects a ChArUco board while the camera is being calibrated.
    pub charuco: Option<Arc<Mutex<Charuco>>>,
}

impl Processing {
    /// Processing for a configured camera at its configured mode, outside calibration.
    pub fn new(
        camera: &CameraConfig,
        config: &RobotConfig,
        layout: Option<Arc<FieldLayout>>,
    ) -> Self {
        Processing {
            calibration: camera.calibration().cloned(),
            mount: camera.mount.isometry(),
            tag_size: pose::TAG_SIZE,
            ignored_tags: config.ignored_tags.clone(),
            layout,
            charuco: None,
        }
    }
}

pub struct Processed {
    pub width: u32,
    pub height: u32,
    pub detections: Vec<Tag>,
    /// Tags used for the estimate.
    pub used_tags: Vec<u32>,
    pub estimate: Option<Estimate>,
    pub charuco: Option<View>,
    pub timings: Timings,
}

pub struct Timings {
    pub decode: Duration,
    pub detect: Duration,
    pub pose: Duration,
}

/// Processes one camera's frames, keeping its decoder and a detector for the current image size
/// and calibration.
#[derive(Default)]
pub struct Processor {
    decoder: Option<Decoder>,
    detector: Option<Built>,
}

struct Built {
    detector: apriltag::Detector,
    size: (u32, u32),
    calibration: Option<Calibration>,
}

impl Processor {
    pub fn process(&mut self, jpeg: &[u8], processing: &Processing) -> anyhow::Result<Processed> {
        let start = Instant::now();
        let decoder = match &mut self.decoder {
            Some(decoder) => decoder,
            None => self.decoder.insert(Decoder::new()?),
        };
        // Device pixels are only valid until the next decode, so `gray` doesn't outlive this call.
        let gray = decoder.decode(jpeg)?;
        let decoded = Instant::now();

        let size = (gray.width, gray.height);
        let calibration = processing.calibration.as_ref();
        let built = match &mut self.detector {
            Some(built) if built.size == size && built.calibration.as_ref() == calibration => built,
            detector => detector.insert(Built {
                // The calibration, when known, lets the detector fit tag edges in undistorted
                // space.
                detector: apriltag::Detector::new(
                    size.0 as usize,
                    size.1 as usize,
                    apriltag::Config { lens: calibration.map(lens), ..Default::default() },
                )?,
                size,
                calibration: calibration.cloned(),
            }),
        };
        let (width, height) = (size.0 as usize, size.1 as usize);
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
        let detections = built.detector.detect(&source)?;
        let detected = Instant::now();

        let (used_tags, estimate) = estimate(processing, &detections, size);
        let done = Instant::now();

        let charuco = match &processing.charuco {
            Some(charuco) => {
                let host = match &gray.pixels {
                    Pixels::Host(pixels) => pixels.as_slice(),
                    #[cfg(feature = "jetson")]
                    Pixels::Device { .. } => built.detector.host_pixels(),
                    #[cfg(not(feature = "jetson"))]
                    Pixels::Device { .. } => {
                        unreachable!("only Jetson builds decode to device memory")
                    }
                };
                Some(
                    charuco
                        .lock()
                        .unwrap()
                        .detect(host, size.0, size.1)
                        .map_err(|e| anyhow::anyhow!("ChArUco: {e}"))?,
                )
            }
            None => None,
        };

        Ok(Processed {
            width: size.0,
            height: size.1,
            detections,
            used_tags,
            estimate,
            charuco,
            timings: Timings {
                decode: decoded - start,
                detect: detected - decoded,
                pose: done - detected,
            },
        })
    }
}

fn lens(k: &Calibration) -> Lens {
    Lens {
        fx: k.fx as f32,
        fy: k.fy as f32,
        cx: k.cx as f32,
        cy: k.cy as f32,
        distortion: k.distortion.map(|d| d as f32),
    }
}

/// Keeps known, non-ignored tags and solves, assuming rough intrinsics when the camera is
/// uncalibrated.
fn estimate(
    processing: &Processing,
    detections: &[Tag],
    size: (u32, u32),
) -> (Vec<u32>, Option<Estimate>) {
    let Some(layout) = &processing.layout else {
        return (Vec::new(), None);
    };
    let calibration = processing.calibration.clone().unwrap_or_else(|| Calibration::assumed(size));
    let tags: Vec<TagObservation> = detections
        .iter()
        .filter(|d| !processing.ignored_tags.contains(&d.id))
        // Corners past where the lens model inverts would corrupt the fit.
        .filter(|d| d.corners.iter().all(|&p| pose::undistort(p, &calibration).is_some()))
        .filter_map(|d| {
            Some(TagObservation {
                id: d.id,
                pixels: d.corners,
                field: pose::tag_corners(layout.tags.get(&d.id)?, processing.tag_size),
            })
        })
        .collect();
    let used = tags.iter().map(|t| t.id).collect();
    (used, pose::solve(&tags, &calibration, &processing.mount, size))
}

#[cfg(test)]
mod tests {
    use super::*;

    const DIR: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/regression");

    /// The camera that rendered the fixtures; `rotated.jpg` was rendered upside down.
    fn processing(rotated: bool) -> Processing {
        let (roll, cx, cy, p1, p2) =
            if rotated { (180, 639, 399, -0.006, 0.008) } else { (0, 640, 400, 0.006, -0.008) };
        let config = RobotConfig::parse(&format!(
            "[cameras.front]\nserial = \"front\"\nmount = {{ z = 0.6, roll = {roll} }}\n\
             [cameras.front.calibrations.1280x800]\nfx = 700\nfy = 700\ncx = {cx}\ncy = {cy}\n\
             distortion = [-0.18, 0.04, {p1}, {p2}, 0.01]\n"
        ))
        .unwrap();
        let layout = std::fs::read_to_string(format!("{DIR}/layout.json")).unwrap();
        let layout = Arc::new(FieldLayout::parse(&layout).unwrap());
        Processing {
            // The fixtures were rendered with larger tags than FRC uses.
            tag_size: 0.3,
            ..Processing::new(&config.cameras["front"], &config, Some(layout))
        }
    }

    fn process(image: &str, processing: &Processing) -> Processed {
        let jpeg = std::fs::read(format!("{DIR}/{image}")).unwrap();
        Processor::default().process(&jpeg, processing).unwrap()
    }

    #[test]
    fn regression_images_produce_expected_poses() {
        let manifest: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(format!("{DIR}/manifest.json")).unwrap())
                .unwrap();
        for case in manifest["cases"].as_array().unwrap() {
            let name = case["name"].as_str().unwrap();
            let processing = processing(case["rotated"].as_bool().unwrap_or(false));
            let processed = process(case["image"].as_str().unwrap(), &processing);
            let mut ids: Vec<u32> = processed.detections.iter().map(|d| d.id).collect();
            ids.sort();
            let expected: Vec<u32> = case["tags"]
                .as_array()
                .unwrap()
                .iter()
                .map(|t| t["id"].as_u64().unwrap() as u32)
                .collect();
            assert_eq!(ids, expected, "{name}");
            let Some(translation) = case["robot_translation_m"].as_array() else {
                assert!(processed.estimate.is_none(), "{name}");
                continue;
            };
            let estimate = processed.estimate.unwrap_or_else(|| panic!("{name}: no estimate"));
            let pose = estimate.primary.pose;
            let truth = nalgebra::Vector3::new(
                translation[0].as_f64().unwrap(),
                translation[1].as_f64().unwrap(),
                translation[2].as_f64().unwrap(),
            );
            let q = case["robot_quaternion_wxyz"].as_array().unwrap();
            let q: Vec<f64> = q.iter().map(|v| v.as_f64().unwrap()).collect();
            let rotation = nalgebra::UnitQuaternion::from_quaternion(nalgebra::Quaternion::new(
                q[0], q[1], q[2], q[3],
            ));
            let translation_error = (pose.translation.vector - truth).norm();
            let rotation_error = pose.rotation.angle_to(&rotation).to_degrees();
            assert!(
                translation_error < case["max_translation_error_m"].as_f64().unwrap(),
                "{name}: {pose}"
            );
            assert!(
                rotation_error < case["max_rotation_error_deg"].as_f64().unwrap(),
                "{name}: {pose}"
            );
            assert!(
                estimate.primary.error < case["max_reprojection_error_px"].as_f64().unwrap(),
                "{name}"
            );
        }
    }

    #[test]
    fn uncalibrated_camera_still_estimates() {
        let processing = Processing { calibration: None, ..processing(false) };
        let processed = process("center.jpg", &processing);
        assert_eq!(processed.used_tags, vec![1]);
        // The fixture is 2 m away; assumed intrinsics only get the distance roughly right.
        let distance = processed.estimate.unwrap().average_tag_distance;
        assert!((1.5..2.5).contains(&distance), "{distance}");
    }

    #[test]
    fn detects_corners_in_order_without_a_layout() {
        let processing = Processing { calibration: None, layout: None, ..processing(false) };
        let processed = process("center.jpg", &processing);
        assert!(processed.estimate.is_none());
        assert_eq!(processed.detections.len(), 1);
        let expected = [[587.43, 452.55], [692.32, 452.43], [692.22, 347.76], [587.53, 347.64]];
        for (corner, expected) in processed.detections[0].corners.iter().zip(expected) {
            assert!((corner[0] - expected[0]).hypot(corner[1] - expected[1]) < 0.5, "{corner:?}");
        }
    }
}
