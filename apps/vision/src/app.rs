//! Spot's state: configuration sources, cameras, and status reporting.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tokio::sync::watch;
use utoipa::ToSchema;

use crate::calibration::{self, Board, Charuco, Coverage, Solution, View};
use crate::camera::{Device, Discovery};
use crate::clock::monotonic_us;
use crate::config::{CameraConfig, FieldLayout, FieldView, RobotConfig};
use crate::health::{
    self, CameraSnapshot, CameraState, CameraStatus, Frames, SpotSnapshot, SpotState,
};
use crate::nt::{self, Nt, NtValue};
use crate::overrides;
use crate::pipeline::{Camera, FrameResult, Sink, Target};
use crate::processor::Processing;
use crate::recording::Recorder;
use crate::structs;

/// Where this build came from, when it was built from a Git checkout.
pub struct Build {
    /// Short commit, with `-dirty` when built from uncommitted changes.
    pub revision: Option<String>,
    /// Unix time of the commit.
    pub commit_time: Option<i64>,
}

/// Jetson-local settings, kept out of the robot config.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, ToSchema)]
pub struct Settings {
    pub team: Option<u16>,
    /// NetworkTables server host, overriding the team number's robot address.
    pub nt_server: Option<String>,
    /// The printed calibration board.
    #[serde(default)]
    #[schema(required = true)]
    pub calibration_board: Board,
}

impl Settings {
    fn servers(&self) -> Vec<String> {
        if let Some(server) = self.nt_server.as_ref().filter(|s| !s.is_empty()) {
            return vec![server.clone()];
        }
        match self.team {
            Some(team) => vec![
                format!("10.{}.{}.2", team / 100, team % 100),
                format!("roboRIO-{team}-FRC.local"),
            ],
            None => Vec::new(),
        }
    }
}

/// The configuration that cameras run with.
#[derive(Clone)]
struct Effective {
    config: RobotConfig,
    layout: Option<Arc<FieldLayout>>,
}

struct Inner {
    settings: Settings,
    robot_config: Option<String>,
    robot_config_live: bool,
    field_layout: Option<String>,
    overrides: Map<String, Value>,
    merged: String,
    /// The last valid configuration keeps running while a newer one is invalid.
    effective: Option<Effective>,
    config_error: Option<String>,
    devices: Vec<Device>,
    cameras: BTreeMap<String, Camera>,
    statuses: Vec<CameraStatus>,
    health: health::Cameras,
    sessions: HashMap<String, Session>,
}

/// A camera calibration in progress.
struct Session {
    board: Board,
    /// Detects the board in the camera's frames.
    charuco: Arc<Mutex<Charuco>>,
    size: Option<(u32, u32)>,
    latest: View,
    frames: Vec<View>,
    coverage: Coverage,
    /// Whether views are captured automatically as the board moves.
    capturing: bool,
    /// Why the latest view wasn't captured.
    reason: String,
    solution: Option<Solution>,
}

impl Session {
    /// Captures the latest view when it adds coverage.
    fn auto_capture(&mut self) {
        let Some(size) = self.size else { return };
        match self.coverage.skip_reason(&self.latest, &self.frames, size) {
            Some(reason) => self.reason = reason,
            None => {
                self.frames.push(self.latest.clone());
                self.coverage = Coverage::new(&self.frames, &self.board, size);
                self.solution = None;
                self.reason = "Captured a view".into();
            }
        }
    }
}

pub struct App {
    state_dir: PathBuf,
    system: crate::system::System,
    build: Build,
    recorder: Arc<Recorder>,
    discovery: Discovery,
    nt: OnceLock<Arc<Nt>>,
    servers: watch::Sender<Vec<String>>,
    inner: Mutex<Inner>,
}

const SETTINGS: &str = "settings.json";
const ROBOT_CONFIG: &str = "robot-config.toml";
const FIELD_LAYOUT: &str = "field-layout.json";
const OVERRIDES: &str = "overrides.json";

fn write_atomic(path: &Path, contents: &[u8]) {
    let temporary = path.with_extension("tmp");
    let result =
        std::fs::write(&temporary, contents).and_then(|()| std::fs::rename(&temporary, path));
    if let Err(error) = result {
        tracing::error!(path = %path.display(), %error, "could not save");
    }
}

impl App {
    pub fn new(
        state_dir: &Path,
        replay: Option<&Path>,
        default_team: Option<u16>,
        build: Build,
        recorder: Arc<Recorder>,
    ) -> Arc<App> {
        let read = |name: &str| std::fs::read_to_string(state_dir.join(name)).ok();
        let settings = read(SETTINGS)
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or(Settings { team: default_team, ..Default::default() });
        let overrides =
            read(OVERRIDES).and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
        let app = Arc::new(App {
            state_dir: state_dir.to_path_buf(),
            system: Default::default(),
            build,
            recorder,
            discovery: Discovery::new(replay),
            nt: OnceLock::new(),
            servers: watch::Sender::new(settings.servers()),
            inner: Mutex::new(Inner {
                settings,
                robot_config: read(ROBOT_CONFIG),
                robot_config_live: false,
                field_layout: read(FIELD_LAYOUT),
                overrides,
                merged: String::new(),
                effective: None,
                config_error: None,
                devices: Vec::new(),
                cameras: BTreeMap::new(),
                statuses: Vec::new(),
                health: health::Cameras::default(),
                sessions: HashMap::new(),
            }),
        });
        let mut inner = app.inner.lock().unwrap();
        app.recompute(&mut inner);
        drop(inner);
        app
    }

    pub fn start(self: &Arc<Self>) {
        let nt = Nt::spawn(self.servers.subscribe(), Arc::new(self.clone()));
        self.recorder.set_clock(nt.clone());
        let _ = self.nt.set(nt);
        let recorder = self.recorder.clone();
        tokio::spawn(async move {
            if let Err(error) = recorder.serve().await {
                tracing::error!(%error, "could not start the Foxglove server");
            }
        });
        let app = self.clone();
        std::thread::Builder::new()
            .name("supervisor".into())
            .spawn(move || {
                loop {
                    app.tick();
                    std::thread::sleep(Duration::from_millis(500));
                }
            })
            .unwrap();
        let app = self.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_millis(250));
            loop {
                interval.tick().await;
                app.publish_status();
                app.recorder.status(&app.status());
            }
        });
    }

    fn nt(&self) -> &Nt {
        self.nt.get().expect("started")
    }

    /// Rebuilds the effective config from its sources and applies it to cameras.
    fn recompute(self: &Arc<Self>, inner: &mut Inner) {
        if let Some(robot) =
            inner.robot_config.as_deref().and_then(|t| overrides::toml_to_json(t).ok())
        {
            let before = inner.overrides.clone();
            overrides::prune(&robot, &mut inner.overrides);
            if inner.overrides != before {
                write_atomic(
                    &self.state_dir.join(OVERRIDES),
                    &serde_json::to_vec_pretty(&inner.overrides).unwrap(),
                );
            }
        }
        let robot = inner.robot_config.as_deref().unwrap_or("");
        let result = overrides::merge(robot, &inner.overrides).and_then(|merged| {
            let config = RobotConfig::parse(&merged)?;
            let layout = inner.field_layout.as_deref().map(FieldLayout::parse).transpose()?;
            Ok((merged, Effective { config, layout: layout.map(Arc::new) }))
        });
        let error = match result {
            Ok((merged, effective)) => {
                self.recorder.set_config(&effective.config, effective.layout.clone());
                inner.merged = merged;
                inner.effective = Some(effective);
                None
            }
            Err(error) => Some(error),
        };
        if error != inner.config_error {
            match &error {
                Some(error) => {
                    tracing::warn!(%error, "config rejected; keeping the last valid config")
                }
                None => tracing::info!("config applied"),
            }
            inner.config_error = error;
        }
        self.reconcile(inner);
    }

    /// Starts, stops, and retargets cameras to match the effective config and devices.
    fn reconcile(self: &Arc<Self>, inner: &mut Inner) {
        let Some(effective) = inner.effective.clone() else { return };
        let config = &effective.config;
        inner.cameras.retain(|name, _| config.cameras.contains_key(name));
        for (name, camera) in &config.cameras {
            let target = Target {
                device: resolve(&inner.devices, camera).ok(),
                mode: camera.mode,
                controls: camera.controls.clone(),
            };
            let processing = Processing {
                charuco: inner.sessions.get(name).map(|s| s.charuco.clone()),
                ..Processing::new(camera, config, effective.layout.clone())
            };
            match inner.cameras.get(name) {
                Some(running) => running.configure(target, processing),
                None => {
                    let sink: Arc<dyn Sink> = self.clone();
                    inner
                        .cameras
                        .insert(name.clone(), Camera::start(name, target, processing, sink));
                }
            }
        }
    }

    fn tick(self: &Arc<Self>) {
        let devices = self.discovery.devices();
        let mut inner = self.inner.lock().unwrap();
        if devices != inner.devices {
            inner.devices = devices;
            self.reconcile(&mut inner);
        }
        let inner = &mut *inner;
        let mut snapshots = Vec::new();
        if let Some(effective) = &inner.effective {
            for (name, config) in &effective.config.cameras {
                let Some(camera) = inner.cameras.get(name) else { continue };
                let counters = camera.counters();
                let load = |c: &AtomicU64| c.load(Ordering::Relaxed);
                snapshots.push(CameraSnapshot {
                    name,
                    config,
                    device: resolve(&inner.devices, config),
                    streaming: camera.streaming(),
                    error: camera.error(),
                    frames: Frames {
                        captured: load(&counters.captured),
                        processed: load(&counters.processed),
                        dropped: load(&counters.dropped),
                    },
                });
            }
        }
        inner.statuses = inner.health.statuses(Instant::now(), snapshots);
        let _ = sd_notify::notify(&[sd_notify::NotifyState::Watchdog]);
    }

    fn state(&self, inner: &Inner) -> (SpotState, String) {
        health::spot_state(&SpotSnapshot {
            synced: self.nt().synced(),
            servers: &self.servers.borrow(),
            has_config: inner.robot_config.is_some(),
            has_field_layout: inner.field_layout.is_some(),
            config_error: inner.config_error.as_deref(),
            cameras: &inner.statuses,
        })
    }

    fn publish_status(&self) {
        let nt = self.nt();
        let now = monotonic_us();
        let inner = self.inner.lock().unwrap();
        let (state, error) = self.state(&inner);
        self.recorder.tick();
        let status = structs::spot_status(
            self.build.revision.as_deref().unwrap_or_default(),
            state,
            !inner.overrides.is_empty(),
        );
        nt.publish("/Spot/outputs/status", "struct:SpotStatus", NtValue::Raw(status), now);
        nt.publish("/Spot/outputs/error", "string", NtValue::String(error), now);
        for camera in &inner.statuses {
            let status = structs::spot_camera_status(camera);
            let topic = format!("/Spot/outputs/cameras/{}/status", camera.name);
            nt.publish(&topic, "struct:SpotCameraStatus", NtValue::Raw(status), now);
        }
    }

    /// Replaces a robot-provided input and caches it for bench use without a robot.
    fn set_input(self: &Arc<Self>, file: &str, value: String) {
        let mut inner = self.inner.lock().unwrap();
        let slot =
            if file == ROBOT_CONFIG { &mut inner.robot_config } else { &mut inner.field_layout };
        if slot.as_ref() == Some(&value) {
            inner.robot_config_live |= file == ROBOT_CONFIG;
            return;
        }
        write_atomic(&self.state_dir.join(file), value.as_bytes());
        *slot = Some(value);
        inner.robot_config_live |= file == ROBOT_CONFIG;
        self.recompute(&mut inner);
    }

    pub fn status(&self) -> Status {
        let inner = self.inner.lock().unwrap();
        let (state, error) = self.state(&inner);
        let nt = self.nt();
        Status {
            revision: self.build.revision.clone(),
            commit_time: self.build.commit_time,
            state,
            error,
            overrides_active: !inner.overrides.is_empty(),
            nt: NtStatus { server: nt.server(), time_synced: nt.synced() },
            cameras: inner.statuses.clone(),
        }
    }

    pub fn devices(&self) -> Vec<DeviceStatus> {
        let inner = self.inner.lock().unwrap();
        inner
            .devices
            .iter()
            .map(|device| DeviceStatus {
                camera: inner.effective.as_ref().and_then(|e| {
                    e.config
                        .cameras
                        .iter()
                        .find(|(_, c)| resolve(&inner.devices, c).ok().as_ref() == Some(device))
                        .map(|(name, _)| name.clone())
                }),
                device: device.clone(),
            })
            .collect()
    }

    pub fn config(&self) -> ConfigView {
        let inner = self.inner.lock().unwrap();
        ConfigView {
            robot_config: inner.robot_config.clone(),
            robot_config_live: inner.robot_config_live,
            field_layout: inner
                .effective
                .as_ref()
                .and_then(|e| e.layout.as_ref())
                .map(|l| l.view()),
            overrides: inner.overrides.clone(),
            merged: inner.merged.clone(),
            config: inner.effective.as_ref().map(|e| e.config.clone()),
            error: inner.config_error.clone(),
        }
    }

    /// Replaces the dashboard overrides. Rejected overrides are not saved.
    pub fn set_overrides(
        self: &Arc<Self>,
        overrides: Map<String, Value>,
    ) -> Result<ConfigView, String> {
        let mut inner = self.inner.lock().unwrap();
        let robot = inner.robot_config.as_deref().unwrap_or("");
        RobotConfig::parse(&overrides::merge(robot, &overrides)?)?;
        write_atomic(
            &self.state_dir.join(OVERRIDES),
            &serde_json::to_vec_pretty(&overrides).unwrap(),
        );
        inner.overrides = overrides;
        self.recompute(&mut inner);
        drop(inner);
        Ok(self.config())
    }

    pub fn settings(&self) -> Settings {
        self.inner.lock().unwrap().settings.clone()
    }

    pub fn set_settings(&self, settings: Settings) {
        write_atomic(
            &self.state_dir.join(SETTINGS),
            &serde_json::to_vec_pretty(&settings).unwrap(),
        );
        self.servers.send_replace(settings.servers());
        self.inner.lock().unwrap().settings = settings;
    }

    pub fn system(&self) -> crate::system::SystemStatus {
        self.system.read(&self.state_dir)
    }

    /// Starts calibrating a camera, discarding any previous session.
    pub fn start_calibration(self: &Arc<Self>, camera: &str) -> Result<CalibrationView, String> {
        let mut inner = self.inner.lock().unwrap();
        if !inner.cameras.contains_key(camera) {
            return Err(format!("No camera named {camera:?}"));
        }
        let board = inner.settings.calibration_board.clone();
        let session = Session {
            charuco: Arc::new(Mutex::new(Charuco::new(&board)?)),
            board,
            size: None,
            latest: View::default(),
            frames: Vec::new(),
            coverage: Coverage::default(),
            capturing: true,
            reason: String::new(),
            solution: None,
        };
        inner.sessions.insert(camera.to_string(), session);
        self.reconcile(&mut inner);
        drop(inner);
        self.calibration(camera)
    }

    pub fn calibration(&self, camera: &str) -> Result<CalibrationView, String> {
        let inner = self.inner.lock().unwrap();
        let session = inner.sessions.get(camera).ok_or("This camera is not being calibrated")?;
        Ok(CalibrationView {
            camera: camera.to_string(),
            board: session.board.clone(),
            width: session.size.map(|s| s.0),
            height: session.size.map(|s| s.1),
            frames: session.frames.clone(),
            latest: session.latest.clone(),
            coverage: session.coverage.clone(),
            capturing: session.capturing,
            reason: session.reason.clone(),
            solution: session.solution.clone(),
            min_frames: calibration::MIN_FRAMES as u32,
            max_rms: calibration::MAX_RMS,
        })
    }

    /// Pauses or resumes capturing views automatically.
    pub fn set_capturing(&self, camera: &str, capturing: bool) -> Result<CalibrationView, String> {
        {
            let mut inner = self.inner.lock().unwrap();
            let session =
                inner.sessions.get_mut(camera).ok_or("This camera is not being calibrated")?;
            session.capturing = capturing;
        }
        self.calibration(camera)
    }

    pub fn solve_calibration(&self, camera: &str) -> Result<CalibrationView, String> {
        let (board, frames, size) = {
            let mut inner = self.inner.lock().unwrap();
            let session =
                inner.sessions.get_mut(camera).ok_or("This camera is not being calibrated")?;
            // New views would discard the solution before it can be applied.
            session.capturing = false;
            (session.board.clone(), session.frames.clone(), session.size.ok_or("No frames yet")?)
        };
        // A separate board, so the camera keeps detecting while this solves.
        let solution = Charuco::new(&board)?.solve(&frames, size)?;
        if let Some(session) = self.inner.lock().unwrap().sessions.get_mut(camera) {
            session.solution = Some(solution);
        }
        self.calibration(camera)
    }

    pub fn stop_calibration(self: &Arc<Self>, camera: &str) {
        let mut inner = self.inner.lock().unwrap();
        if inner.sessions.remove(camera).is_some() {
            self.reconcile(&mut inner);
        }
    }

    pub fn recorder(&self) -> &Recorder {
        &self.recorder
    }
}

/// Finds a camera's device by serial, using the port only to tell apart devices that share
/// the serial.
fn resolve(devices: &[Device], camera: &CameraConfig) -> Result<Device, (CameraState, String)> {
    let serial = &camera.serial;
    let matching: Vec<&Device> =
        devices.iter().filter(|d| d.serial.as_ref() == Some(serial)).collect();
    match (matching.as_slice(), &camera.port) {
        ([device], _) => Ok((*device).clone()),
        ([], _) => Err((CameraState::Disconnected, format!("No camera with serial {serial:?}"))),
        (shared, Some(port)) => match shared.iter().find(|d| d.port.as_ref() == Some(port)) {
            Some(device) => Ok((*device).clone()),
            None => Err((
                CameraState::Disconnected,
                format!("No camera with serial {serial:?} on port {port:?}"),
            )),
        },
        (shared, None) => Err((
            CameraState::DuplicateSerial,
            format!("{} cameras share serial {serial:?}; set a port", shared.len()),
        )),
    }
}

impl Sink for App {
    fn frame(&self, result: &FrameResult) {
        self.recorder.frame(result);
        if let Some(view) = &result.charuco
            && let Some(session) = self.inner.lock().unwrap().sessions.get_mut(result.camera)
        {
            session.size = Some((result.width, result.height));
            session.latest = view.clone();
            if session.capturing {
                session.auto_capture();
            }
        }
        let Some(estimate) = &result.estimate else { return };
        let topic = format!("/Spot/outputs/cameras/{}/estimate", result.camera);
        let value = NtValue::Raw(structs::spot_estimate(estimate));
        self.nt().publish(&topic, "struct:SpotEstimate", value, result.monotonic_us);
    }
}

impl nt::Handler for Arc<App> {
    fn value(&self, topic: &str, value: rmpv::Value) {
        match topic {
            "/Spot/inputs/config" => {
                if let Some(toml) = value.as_str() {
                    self.set_input(ROBOT_CONFIG, toml.to_string());
                }
            }
            "/Spot/inputs/fieldLayout" => {
                if let Some(json) = value.as_str() {
                    self.set_input(FIELD_LAYOUT, json.to_string());
                }
            }
            _ => {
                if let Some(key) = topic.strip_prefix("/FMSInfo/") {
                    self.recorder.set_fms(key, &value);
                }
            }
        }
    }

    fn connection_changed(&self) {
        let mut inner = self.inner.lock().unwrap();
        if self.nt().server().is_none() {
            inner.robot_config_live = false;
        }
    }
}

#[derive(Serialize, ToSchema)]
pub struct Status {
    /// Short Git commit Spot was built from, with `-dirty` for uncommitted changes.
    pub revision: Option<String>,
    /// Unix time of that commit.
    pub commit_time: Option<i64>,
    pub state: SpotState,
    /// Details for a non-ready state.
    pub error: String,
    pub overrides_active: bool,
    pub nt: NtStatus,
    pub cameras: Vec<CameraStatus>,
}

#[derive(Serialize, ToSchema)]
pub struct NtStatus {
    pub server: Option<String>,
    pub time_synced: bool,
}

#[derive(Serialize, ToSchema)]
pub struct DeviceStatus {
    #[serde(flatten)]
    pub device: Device,
    /// The configured camera using this device.
    pub camera: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct ConfigView {
    /// The robot's TOML, live or cached from the last connection.
    pub robot_config: Option<String>,
    /// Whether the robot config came from the robot during this connection.
    pub robot_config_live: bool,
    /// The running field layout.
    pub field_layout: Option<FieldView>,
    /// Dashboard overrides: a deep-partial config where `null` removes a key.
    #[schema(value_type = HashMap<String, serde_json::Value>)]
    pub overrides: Map<String, Value>,
    /// Robot TOML with overrides applied, ready to copy into robot code.
    pub merged: String,
    /// The running config.
    pub config: Option<RobotConfig>,
    /// Why the latest config was rejected.
    pub error: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct CalibrationView {
    pub camera: String,
    pub board: Board,
    /// Image size, once a frame has been seen.
    pub width: Option<u32>,
    pub height: Option<u32>,
    /// Captured views.
    pub frames: Vec<View>,
    /// Board corners in the most recent frame.
    pub latest: View,
    pub coverage: Coverage,
    /// Whether views are captured automatically as the board moves.
    pub capturing: bool,
    /// Why the latest view wasn't captured.
    pub reason: String,
    pub solution: Option<Solution>,
    pub min_frames: u32,
    /// RMS error in pixels above which a solution is not accepted.
    pub max_rms: f64,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn device(serial: &str, port: &str) -> Device {
        Device {
            path: format!("/dev/{port}"),
            serial: Some(serial.into()),
            port: Some(port.into()),
            product: String::new(),
            modes: Vec::new(),
            controls: Vec::new(),
        }
    }

    fn camera(serial: &str, port: Option<&str>) -> CameraConfig {
        let port = port.map_or(String::new(), |p| format!("port = \"{p}\"\n"));
        let config =
            RobotConfig::parse(&format!("[cameras.a]\nserial = \"{serial}\"\n{port}")).unwrap();
        config.cameras["a"].clone()
    }

    #[test]
    fn resolves_by_serial_and_falls_back_to_port_for_shared_serials() {
        let devices = [device("U", "1-2.1"), device("S", "1-2.2"), device("S", "1-2.3")];
        // A unique serial wins even if the camera moved ports.
        assert_eq!(resolve(&devices, &camera("U", Some("1-2.4"))).unwrap().path, "/dev/1-2.1");
        assert_eq!(resolve(&devices, &camera("S", Some("1-2.3"))).unwrap().path, "/dev/1-2.3");
        assert_eq!(
            resolve(&devices, &camera("S", None)).unwrap_err().0,
            CameraState::DuplicateSerial
        );
        assert_eq!(
            resolve(&devices, &camera("S", Some("1-2.4"))).unwrap_err().0,
            CameraState::Disconnected
        );
    }
}
