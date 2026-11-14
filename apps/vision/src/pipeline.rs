//! Per-camera capture and processing threads. Capture always replaces the pending frame,
//! so a slow processor drops frames (counted) instead of adding latency.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

use crate::apriltag::Tag;
use crate::calibration::View;
use crate::camera::{self, Device, Frame};
use crate::config::{Controls, Mode};
use crate::pose::Estimate;
use crate::processor::{Processing, Processor};

/// What to capture.
#[derive(Clone, PartialEq)]
pub struct Target {
    pub device: Option<Device>,
    pub mode: Mode,
    pub controls: Controls,
}

pub struct FrameResult<'a> {
    pub camera: &'a str,
    pub monotonic_us: i64,
    pub jpeg: &'a [u8],
    pub width: u32,
    pub height: u32,
    pub detections: &'a [Tag],
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
    let mut processor = Processor::default();
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
        let result = processor.process(&frame.jpeg, &processing).map(|processed| {
            sink.frame(&FrameResult {
                camera: &shared.name,
                monotonic_us: frame.monotonic_us,
                jpeg: &frame.jpeg,
                width: processed.width,
                height: processed.height,
                detections: &processed.detections,
                used_tags: processed.used_tags,
                estimate: processed.estimate,
                charuco: processed.charuco,
            });
        });
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
