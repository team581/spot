//! Camera discovery and MJPEG capture.

use std::path::{Path, PathBuf};

use serde::Serialize;
use utoipa::ToSchema;

use crate::config::{Controls, Mode};

mod replay;
#[cfg(target_os = "linux")]
mod v4l2;

/// A captured JPEG with its kernel capture timestamp.
pub struct Frame {
    pub jpeg: Vec<u8>,
    pub monotonic_us: i64,
}

/// A physical camera.
#[derive(Debug, Clone, PartialEq, Serialize, ToSchema)]
pub struct Device {
    /// Device node, or the image file for a replay camera.
    pub path: String,
    pub serial: Option<String>,
    /// Physical port label, when plugged into a labeled port.
    pub port: Option<String>,
    pub product: String,
    /// Supported MJPEG modes.
    pub modes: Vec<Mode>,
    pub controls: Vec<ControlRange>,
}

/// A configurable control's range.
#[derive(Debug, Clone, PartialEq, Serialize, ToSchema)]
pub struct ControlRange {
    /// `auto_exposure`, `exposure_time_absolute`, or `gain`
    pub name: String,
    pub min: i64,
    pub max: i64,
    pub step: i64,
    pub default: i64,
}

pub trait Source: Send {
    /// Blocks until the next frame.
    fn next(&mut self) -> anyhow::Result<Frame>;
    fn apply(&mut self, controls: &Controls) -> anyhow::Result<()>;
}

/// Finds cameras: V4L2 devices, or a folder of JPEGs for development.
#[derive(Default)]
pub struct Discovery {
    replay: Option<PathBuf>,
    #[cfg(target_os = "linux")]
    cache: std::sync::Mutex<v4l2::Cache>,
}

impl Discovery {
    // The cache only exists on Linux.
    #[allow(clippy::needless_update)]
    pub fn new(replay: Option<&Path>) -> Self {
        Self { replay: replay.map(Path::to_path_buf), ..Default::default() }
    }

    pub fn devices(&self) -> Vec<Device> {
        if let Some(dir) = &self.replay {
            return replay::devices(dir);
        }
        #[cfg(target_os = "linux")]
        return v4l2::devices(&mut self.cache.lock().unwrap());
        #[cfg(not(target_os = "linux"))]
        Vec::new()
    }
}

pub fn open(device: &Device, mode: Mode, controls: &Controls) -> anyhow::Result<Box<dyn Source>> {
    if Path::new(&device.path).starts_with("/dev") {
        #[cfg(target_os = "linux")]
        return v4l2::open(device, mode, controls);
    }
    replay::open(device, mode, controls)
}
