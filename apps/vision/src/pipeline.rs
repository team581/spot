//! Per-camera capture and processing threads. Capture always replaces the pending frame,
//! so a slow processor drops frames (counted) instead of adding latency.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

use nalgebra::Isometry3;

use crate::calibration::{Charuco, View};
use crate::camera::{self, Device, Frame};
use crate::config::{Calibration, Controls, FieldLayout, Mode};
use crate::decode::Decoder;
use crate::detect::{Detection, Detector};
use crate::pose::{self, Estimate, TagObservation};

/// What to capture.
#[derive(Clone, PartialEq)]
pub struct Target {
    pub device: Option<Device>,
    pub mode: Mode,
    pub controls: Controls,
}

/// How to turn detections into an estimate.
pub struct Processing {
    pub calibration: Option<Calibration>,
    pub mount: Isometry3<f64>,
    pub tag_size: f64,
    pub ignored_tags: Vec<u32>,
    pub layout: Option<Arc<FieldLayout>>,
    /// Detects a ChArUco board while the camera is being calibrated.
    pub charuco: Option<Arc<Mutex<Charuco>>>,
}

pub struct FrameResult<'a> {
    pub camera: &'a str,
    pub monotonic_us: i64,
    pub jpeg: &'a [u8],
    pub width: u32,
    pub height: u32,
    pub detections: &'a [Detection],
    /// Tags used for the estimate.
    pub used_tags: Vec<u32>,
    pub estimate: Option<Estimate>,
    pub charuco: Option<View>,
}

pub trait Sink: Send + Sync + 'static {
    fn frame(&self, result: &FrameResult);
}

#[derive(Default)]
pub struct Counters {
    pub captured: AtomicU64,
    pub processed: AtomicU64,
    pub dropped: AtomicU64,
}

struct Shared {
    name: String,
    target: Mutex<Target>,
    processing: Mutex<Arc<Processing>>,
    slot: Mutex<Option<Frame>>,
    wake: Condvar,
    stop: AtomicBool,
    counters: Counters,
    /// `Ok(true)` while streaming; the last capture error otherwise.
    capture: Mutex<Result<bool, String>>,
    process_error: Mutex<Option<String>>,
}

/// A running camera. Dropping it stops its threads.
pub struct Camera(Arc<Shared>);

impl Camera {
    pub fn start(name: &str, target: Target, processing: Processing, sink: Arc<dyn Sink>) -> Self {
        let shared = Arc::new(Shared {
            name: name.to_string(),
            target: Mutex::new(target),
            processing: Mutex::new(Arc::new(processing)),
            slot: Mutex::new(None),
            wake: Condvar::new(),
            stop: AtomicBool::new(false),
            counters: Counters::default(),
            capture: Mutex::new(Ok(false)),
            process_error: Mutex::new(None),
        });
        let capture = shared.clone();
        std::thread::Builder::new()
            .name(format!("capture-{name}"))
            .spawn(move || capture_loop(&capture))
            .unwrap();
        let process = shared.clone();
        std::thread::Builder::new()
            .name(format!("process-{name}"))
            .spawn(move || process_loop(&process, &*sink))
            .unwrap();
        Camera(shared)
    }

    pub fn configure(&self, target: Target, processing: Processing) {
        *self.0.target.lock().unwrap() = target;
        *self.0.processing.lock().unwrap() = Arc::new(processing);
    }

    pub fn counters(&self) -> &Counters {
        &self.0.counters
    }

    pub fn streaming(&self) -> bool {
        matches!(*self.0.capture.lock().unwrap(), Ok(true))
    }

    /// The latest capture or processing problem.
    pub fn error(&self) -> Option<String> {
        if let Err(error) = &*self.0.capture.lock().unwrap() {
            return Some(error.clone());
        }
        self.0.process_error.lock().unwrap().clone()
    }
}

impl Drop for Camera {
    fn drop(&mut self) {
        self.0.stop.store(true, Ordering::Relaxed);
        self.0.wake.notify_all();
    }
}

fn capture_loop(shared: &Shared) {
    let mut backoff = Duration::from_millis(250);
    while !shared.stop.load(Ordering::Relaxed) {
        let target = shared.target.lock().unwrap().clone();
        let Some(device) = &target.device else {
            *shared.capture.lock().unwrap() = Ok(false);
            std::thread::sleep(Duration::from_millis(250));
            continue;
        };
        let mut source = match camera::open(device, target.mode, &target.controls) {
            Ok(source) => source,
            Err(error) => {
                tracing::warn!(camera = shared.name, %error, "could not open camera");
                *shared.capture.lock().unwrap() = Err(format!("{error:#}"));
                std::thread::sleep(backoff);
                backoff = (backoff * 2).min(Duration::from_secs(5));
                continue;
            }
        };
        tracing::info!(camera = shared.name, device = device.path, mode = %target.mode, "streaming");
        backoff = Duration::from_millis(250);
        let mut controls = target.controls.clone();
        let result = loop {
            if shared.stop.load(Ordering::Relaxed) {
                return;
            }
            {
                let current = shared.target.lock().unwrap();
                if current.device != target.device || current.mode != target.mode {
                    break Ok(());
                }
                if current.controls != controls {
                    controls = current.controls.clone();
                    if let Err(error) = source.apply(&controls) {
                        tracing::warn!(camera = shared.name, %error, "could not set controls");
                    }
                }
            }
            match source.next() {
                Ok(frame) => {
                    *shared.capture.lock().unwrap() = Ok(true);
                    shared.counters.captured.fetch_add(1, Ordering::Relaxed);
                    if shared.slot.lock().unwrap().replace(frame).is_some() {
                        shared.counters.dropped.fetch_add(1, Ordering::Relaxed);
                    }
                    shared.wake.notify_one();
                }
                Err(error) => break Err(error),
            }
        };
        match result {
            Ok(()) => *shared.capture.lock().unwrap() = Ok(false),
            Err(error) => {
                tracing::warn!(camera = shared.name, %error, "capture stopped");
                *shared.capture.lock().unwrap() = Err(format!("{error:#}"));
            }
        }
    }
}

fn process_loop(shared: &Shared, sink: &dyn Sink) {
    let mut decoder = None;
    let mut detector: Option<Detector> = None;
    while !shared.stop.load(Ordering::Relaxed) {
        let frame = {
            let mut slot = shared.slot.lock().unwrap();
            loop {
                if let Some(frame) = slot.take() {
                    break frame;
                }
                if shared.stop.load(Ordering::Relaxed) {
                    return;
                }
                slot = shared.wake.wait_timeout(slot, Duration::from_millis(250)).unwrap().0;
            }
        };
        let processing = shared.processing.lock().unwrap().clone();
        let result = (|| -> anyhow::Result<()> {
            if decoder.is_none() {
                decoder = Some(Decoder::new()?);
            }
            let gray = decoder.as_mut().unwrap().decode(&frame.jpeg)?;
            if detector.as_ref().is_none_or(|d| d.size() != (gray.width, gray.height)) {
                detector = Some(Detector::new(gray.width, gray.height)?);
            }
            let detections = detector.as_mut().unwrap().detect(&gray.pixels)?;
            let (used_tags, estimate) =
                estimate(&processing, &detections, (gray.width, gray.height));
            let charuco = match &processing.charuco {
                Some(charuco) => Some(
                    charuco
                        .lock()
                        .unwrap()
                        .detect(&gray.pixels, gray.width, gray.height)
                        .map_err(|e| anyhow::anyhow!("ChArUco: {e}"))?,
                ),
                None => None,
            };
            sink.frame(&FrameResult {
                camera: &shared.name,
                monotonic_us: frame.monotonic_us,
                jpeg: &frame.jpeg,
                width: gray.width,
                height: gray.height,
                detections: &detections,
                used_tags,
                estimate,
                charuco,
            });
            Ok(())
        })();
        shared.counters.processed.fetch_add(1, Ordering::Relaxed);
        let error = result.err().map(|e| format!("{e:#}"));
        let mut last = shared.process_error.lock().unwrap();
        if error != *last {
            if let Some(error) = &error {
                tracing::warn!(camera = shared.name, %error, "could not process frames");
            }
            *last = error;
        }
    }
}

/// Keeps known, non-ignored tags and solves when the camera is calibrated.
fn estimate(
    processing: &Processing,
    detections: &[Detection],
    size: (u32, u32),
) -> (Vec<u32>, Option<Estimate>) {
    let (Some(calibration), Some(layout)) = (&processing.calibration, &processing.layout) else {
        return (Vec::new(), None);
    };
    let tags: Vec<TagObservation> = detections
        .iter()
        .filter(|d| !processing.ignored_tags.contains(&d.id))
        .filter_map(|d| {
            Some(TagObservation {
                id: d.id,
                pixels: d.corners,
                field: pose::tag_corners(layout.tags.get(&d.id)?, processing.tag_size),
            })
        })
        .collect();
    let used = tags.iter().map(|t| t.id).collect();
    (used, pose::solve(&tags, calibration, &processing.mount, size))
}

#[cfg(all(test, not(feature = "jetson")))]
mod tests {
    use super::*;
    use crate::config::RobotConfig;

    /// The camera that rendered the fixtures; `rotated.png` was rendered upside down.
    fn processing(rotated: bool) -> Processing {
        let (roll, cx, cy, p1, p2) =
            if rotated { (180, 639, 399, -0.006, 0.008) } else { (0, 640, 400, 0.006, -0.008) };
        let config = RobotConfig::parse(&format!(
            "tag_size = 0.3\n[cameras.front]\nserial = \"front\"\nmount = {{ z = 0.6, roll = {roll} }}\n\
             [cameras.front.calibrations.1280x800]\nfx = 700\nfy = 700\ncx = {cx}\ncy = {cy}\n\
             distortion = [-0.18, 0.04, {p1}, {p2}, 0.01]\n"
        ))
        .unwrap();
        let camera = &config.cameras["front"];
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/regression");
        let layout = std::fs::read_to_string(format!("{dir}/layout.json")).unwrap();
        Processing {
            calibration: camera.calibration().cloned(),
            mount: camera.mount.isometry(),
            tag_size: config.tag_size,
            ignored_tags: Vec::new(),
            layout: Some(Arc::new(FieldLayout::parse(&layout).unwrap())),
            charuco: None,
        }
    }

    #[test]
    fn regression_images_produce_expected_poses() {
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/regression");
        let manifest: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(format!("{dir}/manifest.json")).unwrap())
                .unwrap();
        for case in manifest["cases"].as_array().unwrap() {
            let name = case["name"].as_str().unwrap();
            let image = image::open(format!("{dir}/{}", case["image"].as_str().unwrap()))
                .unwrap()
                .to_luma8();
            let (width, height) = image.dimensions();
            let detections = Detector::new(width, height).unwrap().detect(image.as_raw()).unwrap();
            let mut ids: Vec<u32> = detections.iter().map(|d| d.id).collect();
            ids.sort();
            let expected: Vec<u32> = case["tags"]
                .as_array()
                .unwrap()
                .iter()
                .map(|t| t["id"].as_u64().unwrap() as u32)
                .collect();
            assert_eq!(ids, expected, "{name}");
            let (_, estimate) =
                estimate(&processing(case.get("config").is_some()), &detections, (width, height));
            let Some(translation) = case["robot_translation_m"].as_array() else {
                assert!(estimate.is_none(), "{name}");
                continue;
            };
            let estimate = estimate.unwrap_or_else(|| panic!("{name}: no estimate"));
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
}
