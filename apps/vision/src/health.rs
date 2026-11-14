//! Spot's and each camera's state, from snapshots of what Spot knows.

use std::collections::HashMap;
use std::time::Instant;

use serde::Serialize;
use utoipa::ToSchema;

use crate::camera::Device;
use crate::config::{CameraConfig, Mode};

/// Spot's most fundamental problem, in order of precedence.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum SpotState {
    Ready = 0,
    WaitingForTimeSync = 1,
    WaitingForConfig = 2,
    InvalidConfig = 3,
    MissingCamera = 4,
    UncalibratedCamera = 5,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum CameraState {
    Streaming = 0,
    Disconnected = 1,
    DuplicateSerial = 2,
    Uncalibrated = 3,
    FallingBehind = 4,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct CameraStatus {
    pub name: String,
    pub state: CameraState,
    pub required: bool,
    pub mode: Mode,
    pub calibrated: bool,
    /// Device node of the matched camera.
    pub device: Option<String>,
    /// Frames processed per second.
    pub fps: f64,
    /// Frames captured per second.
    pub capture_fps: f64,
    /// Frames dropped since the camera started because processing fell behind.
    pub dropped_frames: u64,
    pub error: Option<String>,
}

/// What Spot knows about itself.
pub struct SpotSnapshot<'a> {
    pub synced: bool,
    /// NetworkTables servers Spot tries.
    pub servers: &'a [String],
    pub has_config: bool,
    pub has_field_layout: bool,
    pub config_error: Option<&'a str>,
    pub cameras: &'a [CameraStatus],
}

/// What Spot knows about a running camera.
pub struct CameraSnapshot<'a> {
    pub name: &'a str,
    pub config: &'a CameraConfig,
    /// The matched device, or why there is none.
    pub device: Result<Device, (CameraState, String)>,
    pub streaming: bool,
    /// The latest capture or processing problem.
    pub error: Option<String>,
    pub frames: Frames,
}

/// Frame counts since a camera started.
#[derive(Debug, Clone, Copy, Default)]
pub struct Frames {
    pub captured: u64,
    pub processed: u64,
    pub dropped: u64,
}

/// The first problem that applies; only required cameras count.
pub fn spot_state(spot: &SpotSnapshot) -> (SpotState, String) {
    if !spot.synced {
        let error = if spot.servers.is_empty() {
            "Set a team number or NetworkTables server".into()
        } else {
            format!("Connecting to NetworkTables at {}", spot.servers.join(", "))
        };
        return (SpotState::WaitingForTimeSync, error);
    }
    if !spot.has_config {
        return (SpotState::WaitingForConfig, "Robot has not published /Spot/inputs/config".into());
    }
    if !spot.has_field_layout {
        return (
            SpotState::WaitingForConfig,
            "Robot has not published /Spot/inputs/fieldLayout".into(),
        );
    }
    if let Some(error) = spot.config_error {
        return (SpotState::InvalidConfig, error.into());
    }
    let required = || spot.cameras.iter().filter(|s| s.required);
    let missing: Vec<String> = required()
        .filter(|s| matches!(s.state, CameraState::Disconnected | CameraState::DuplicateSerial))
        .map(|s| format!("{}: {}", s.name, s.error.as_deref().unwrap_or("disconnected")))
        .collect();
    if !missing.is_empty() {
        return (SpotState::MissingCamera, missing.join("; "));
    }
    let uncalibrated: Vec<String> = required()
        .filter(|s| s.state == CameraState::Uncalibrated)
        .map(|s| format!("{}: no calibration for {}", s.name, s.mode.resolution()))
        .collect();
    if !uncalibrated.is_empty() {
        return (SpotState::UncalibratedCamera, uncalibrated.join("; "));
    }
    (SpotState::Ready, String::new())
}

/// Camera states, with frame rates measured over windows of about a second.
#[derive(Default)]
pub struct Cameras {
    windows: HashMap<String, (Instant, Frames)>,
}

impl Cameras {
    /// The cameras' statuses; cameras left out stop being measured.
    pub fn statuses(&mut self, now: Instant, cameras: Vec<CameraSnapshot>) -> Vec<CameraStatus> {
        self.windows.retain(|name, _| cameras.iter().any(|c| c.name == name));
        cameras.into_iter().map(|camera| self.status(now, camera)).collect()
    }

    fn status(&mut self, now: Instant, camera: CameraSnapshot) -> CameraStatus {
        let frames = camera.frames;
        let (since, start) = *self.windows.entry(camera.name.into()).or_insert((now, frames));
        let elapsed = now.duration_since(since).as_secs_f64();
        let (capture_fps, fps, dropping) = if elapsed > 0.0 {
            let captured = frames.captured.saturating_sub(start.captured);
            let dropped = frames.dropped.saturating_sub(start.dropped);
            (
                captured as f64 / elapsed,
                frames.processed.saturating_sub(start.processed) as f64 / elapsed,
                // More than 5% of captured frames dropped.
                dropped * 20 > captured,
            )
        } else {
            (0.0, 0.0, false)
        };
        if elapsed >= 1.0 {
            self.windows.insert(camera.name.into(), (now, frames));
        }
        let config = camera.config;
        let calibrated = config.calibration().is_some();
        let error = camera.error;
        let (state, error) = match &camera.device {
            Err((state, error)) => (*state, Some(error.clone())),
            Ok(_) if !camera.streaming => {
                (CameraState::Disconnected, error.or(Some("Starting".into())))
            }
            Ok(_) if !calibrated => (
                CameraState::Uncalibrated,
                error.or_else(|| Some(format!("No calibration for {}", config.mode.resolution()))),
            ),
            Ok(_) if dropping => (CameraState::FallingBehind, error),
            Ok(_) => (CameraState::Streaming, error),
        };
        CameraStatus {
            name: camera.name.into(),
            state,
            required: config.required,
            mode: config.mode,
            calibrated,
            device: camera.device.ok().map(|d| d.path),
            fps,
            capture_fps,
            dropped_frames: frames.dropped,
            error,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;
    use crate::config::RobotConfig;

    fn config(calibrated: bool) -> CameraConfig {
        let calibration = if calibrated {
            "[cameras.a.calibrations.1280x800]\nfx = 700\nfy = 700\ncx = 640\ncy = 400\ndistortion = [0, 0, 0, 0, 0]\n"
        } else {
            ""
        };
        let config = RobotConfig::parse(&format!("[cameras.a]\nserial = \"a\"\n{calibration}"));
        config.unwrap().cameras["a"].clone()
    }

    fn device() -> Device {
        Device {
            path: "/dev/video0".into(),
            serial: Some("a".into()),
            port: None,
            product: String::new(),
            modes: Vec::new(),
            controls: Vec::new(),
        }
    }

    fn snapshot<'a>(config: &'a CameraConfig, frames: Frames) -> CameraSnapshot<'a> {
        CameraSnapshot {
            name: "a",
            config,
            device: Ok(device()),
            streaming: true,
            error: None,
            frames,
        }
    }

    fn status(name: &str, state: CameraState, required: bool) -> CameraStatus {
        CameraStatus {
            name: name.into(),
            state,
            required,
            mode: config(true).mode,
            calibrated: state != CameraState::Uncalibrated,
            device: None,
            fps: 0.0,
            capture_fps: 0.0,
            dropped_frames: 0,
            error: None,
        }
    }

    fn state_with(cameras: &[CameraStatus]) -> SpotState {
        let snapshot = SpotSnapshot {
            synced: true,
            servers: &[],
            has_config: true,
            has_field_layout: true,
            config_error: None,
            cameras,
        };
        spot_state(&snapshot).0
    }

    #[test]
    fn only_required_cameras_affect_spot() {
        use CameraState::*;
        assert_eq!(state_with(&[status("a", Disconnected, false)]), SpotState::Ready);
        assert_eq!(state_with(&[status("a", Uncalibrated, false)]), SpotState::Ready);
        assert_eq!(state_with(&[status("a", DuplicateSerial, true)]), SpotState::MissingCamera);
        assert_eq!(state_with(&[status("a", Uncalibrated, true)]), SpotState::UncalibratedCamera);
        // A missing camera is more fundamental than an uncalibrated one.
        assert_eq!(
            state_with(&[status("a", Uncalibrated, true), status("b", Disconnected, true)]),
            SpotState::MissingCamera
        );
        assert_eq!(state_with(&[status("a", FallingBehind, true)]), SpotState::Ready);
    }

    #[test]
    fn spot_reports_the_first_problem() {
        let missing = [status("a", CameraState::Disconnected, true)];
        let mut snapshot = SpotSnapshot {
            synced: false,
            servers: &[],
            has_config: false,
            has_field_layout: false,
            config_error: Some("bad"),
            cameras: &missing,
        };
        assert_eq!(spot_state(&snapshot).0, SpotState::WaitingForTimeSync);
        snapshot.synced = true;
        assert_eq!(spot_state(&snapshot).0, SpotState::WaitingForConfig);
        snapshot.has_config = true;
        assert_eq!(spot_state(&snapshot).0, SpotState::WaitingForConfig);
        snapshot.has_field_layout = true;
        assert_eq!(spot_state(&snapshot), (SpotState::InvalidConfig, "bad".into()));
        snapshot.config_error = None;
        assert_eq!(spot_state(&snapshot).0, SpotState::MissingCamera);
    }

    #[test]
    fn camera_falls_behind_when_it_drops_over_5_percent() {
        let config = config(true);
        let start = Instant::now();
        let second = start + Duration::from_secs(1);
        let frames = |dropped| Frames { captured: 100, processed: 100 - dropped, dropped };
        for (dropped, state) in [(5, CameraState::Streaming), (6, CameraState::FallingBehind)] {
            let mut cameras = Cameras::default();
            cameras.statuses(start, vec![snapshot(&config, Frames::default())]);
            let status = cameras.statuses(second, vec![snapshot(&config, frames(dropped))]);
            assert_eq!(status[0].state, state, "{dropped} dropped");
            assert_eq!(status[0].capture_fps, 100.0);
        }
    }

    #[test]
    fn uncalibrated_and_unstarted_cameras() {
        let mut cameras = Cameras::default();
        let now = Instant::now();
        let uncalibrated = config(false);
        let status = cameras.statuses(now, vec![snapshot(&uncalibrated, Frames::default())]);
        assert_eq!(status[0].state, CameraState::Uncalibrated);
        assert_eq!(status[0].error.as_deref(), Some("No calibration for 1280x800"));

        let calibrated = config(true);
        let starting =
            CameraSnapshot { streaming: false, ..snapshot(&calibrated, Frames::default()) };
        let status = cameras.statuses(now, vec![starting]);
        assert_eq!(status[0].state, CameraState::Disconnected);
        assert_eq!(status[0].error.as_deref(), Some("Starting"));
    }
}
