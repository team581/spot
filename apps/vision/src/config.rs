//! Robot-owned TOML configuration and the WPILib field layout.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::str::FromStr;

use nalgebra::{Isometry3, Quaternion, Translation3, UnitQuaternion, Vector3};
use schemars::JsonSchema;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use utoipa::ToSchema;

/// Spot's configuration, owned by robot code and sent as TOML over NetworkTables.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(deny_unknown_fields)]
#[schemars(title = "Spot configuration")]
pub struct RobotConfig {
    /// Tag IDs that are never used for pose estimation.
    #[serde(default)]
    pub ignored_tags: Vec<u32>,
    #[serde(default)]
    pub recording: RecordingConfig,
    /// Cameras keyed by name. Names appear in NetworkTables topics.
    #[serde(default)]
    pub cameras: BTreeMap<String, CameraConfig>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct RecordingConfig {
    /// Record MCAP files of matches and robot enables.
    #[serde(default = "default_true")]
    pub enabled: bool,
    /// Maximum rate of camera images stored per camera.
    #[serde(default = "default_image_fps")]
    #[schemars(range(min = 0.0))]
    pub image_fps: f64,
    /// Delete the oldest recordings once the disk is fuller than this percentage.
    #[serde(default = "default_disk_usage")]
    #[schemars(range(min = 1.0, max = 99.0))]
    pub max_disk_usage_percent: f64,
}

impl Default for RecordingConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            image_fps: default_image_fps(),
            max_disk_usage_percent: default_disk_usage(),
        }
    }
}

fn default_true() -> bool {
    true
}
fn default_image_fps() -> f64 {
    30.0
}
fn default_disk_usage() -> f64 {
    80.0
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct CameraConfig {
    /// USB serial number.
    pub serial: String,
    /// USB port path, for example `1-2.2`. Only used to tell apart cameras that share a
    /// serial, which is the default for some cameras.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub port: Option<String>,
    /// Spot is not ready unless this camera is streaming and calibrated.
    #[serde(default)]
    pub required: bool,
    /// Capture mode as `WIDTHxHEIGHT@FPS`.
    #[serde(default = "default_mode")]
    pub mode: Mode,
    #[serde(default)]
    pub controls: Controls,
    /// Robot-to-camera transform (WPILib coordinates: +X forward, +Y left, +Z up).
    #[serde(default)]
    pub mount: Mount,
    /// Calibrations keyed by resolution, for example `1280x800`.
    #[serde(default)]
    pub calibrations: BTreeMap<String, Calibration>,
}

fn default_mode() -> Mode {
    Mode { width: 1280, height: 800, fps: 120 }
}

impl CameraConfig {
    pub fn calibration(&self) -> Option<&Calibration> {
        self.calibrations.get(&self.mode.resolution())
    }
}

/// Camera controls. Unset controls are reset to the camera's default.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct Controls {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub auto_exposure: Option<AutoExposure>,
    /// Exposure time in the camera's units (100 µs for UVC cameras). Applies in manual mode.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub exposure_time_absolute: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gain: Option<i32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum AutoExposure {
    Manual,
    AperturePriority,
}

/// Translation in meters and rotation in degrees, as WPILib's `Transform3d` and `Rotation3d`.
/// Positive pitch points the lens down.
#[derive(Debug, Clone, Copy, Default, PartialEq, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct Mount {
    #[serde(default)]
    pub x: f64,
    #[serde(default)]
    pub y: f64,
    #[serde(default)]
    pub z: f64,
    #[serde(default)]
    pub roll: f64,
    #[serde(default)]
    pub pitch: f64,
    #[serde(default)]
    pub yaw: f64,
}

impl Mount {
    /// Camera pose in the robot frame, with the camera's axes in WPILib convention.
    pub fn isometry(&self) -> Isometry3<f64> {
        Isometry3::from_parts(
            Translation3::new(self.x, self.y, self.z),
            UnitQuaternion::from_euler_angles(
                self.roll.to_radians(),
                self.pitch.to_radians(),
                self.yaw.to_radians(),
            ),
        )
    }
}

/// Pinhole intrinsics with OpenCV's five-coefficient distortion model.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct Calibration {
    pub fx: f64,
    pub fy: f64,
    pub cx: f64,
    pub cy: f64,
    /// `[k1, k2, p1, p2, k3]`
    pub distortion: [f64; 5],
    /// RMS reprojection error of the calibration in pixels.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rms: Option<f64>,
}

impl Calibration {
    /// Rough intrinsics for an uncalibrated camera: Swyft's published 1280x800 factory
    /// calibration for its USB camera, scaled to the frame size.
    pub fn assumed((width, height): (u32, u32)) -> Self {
        let (sx, sy) = (width as f64 / 1280.0, height as f64 / 800.0);
        Self {
            fx: 799.4949524650956 * sx,
            fy: 799.8320596652597 * sy,
            cx: 644.0110163765805 * sx,
            cy: 447.8047664027805 * sy,
            distortion: [
                -0.08158965422395571,
                0.08184871658046705,
                0.00036991351895525955,
                0.0006269072380960263,
                -0.062389853780706106,
            ],
            rms: None,
        }
    }
}

/// A capture mode, written `WIDTHxHEIGHT@FPS`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Mode {
    pub width: u32,
    pub height: u32,
    pub fps: u32,
}

impl Mode {
    pub fn resolution(&self) -> String {
        format!("{}x{}", self.width, self.height)
    }
}

impl fmt::Display for Mode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}x{}@{}", self.width, self.height, self.fps)
    }
}

impl FromStr for Mode {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, String> {
        let error = || format!("invalid mode {s:?}, expected WIDTHxHEIGHT@FPS");
        let (resolution, fps) = s.split_once('@').ok_or_else(error)?;
        let (width, height) = parse_resolution(resolution).ok_or_else(error)?;
        let fps = fps.parse().map_err(|_| error())?;
        Ok(Mode { width, height, fps })
    }
}

pub fn parse_resolution(s: &str) -> Option<(u32, u32)> {
    let (width, height) = s.split_once('x')?;
    Some((width.parse().ok()?, height.parse().ok()?))
}

impl Serialize for Mode {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for Mode {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        String::deserialize(deserializer)?.parse().map_err(serde::de::Error::custom)
    }
}

impl utoipa::PartialSchema for Mode {
    fn schema() -> utoipa::openapi::RefOr<utoipa::openapi::schema::Schema> {
        utoipa::openapi::ObjectBuilder::new()
            .schema_type(utoipa::openapi::schema::Type::String)
            .pattern(Some(r"^\d+x\d+@\d+$"))
            .examples(["1280x800@120"])
            .into()
    }
}

impl ToSchema for Mode {}

impl JsonSchema for Mode {
    fn schema_name() -> std::borrow::Cow<'static, str> {
        "Mode".into()
    }
    fn json_schema(_: &mut schemars::SchemaGenerator) -> schemars::Schema {
        schemars::json_schema!({
            "type": "string",
            "pattern": r"^\d+x\d+@\d+$",
            "description": "Capture mode as WIDTHxHEIGHT@FPS",
            "examples": ["1280x800@120"],
        })
    }
}

impl RobotConfig {
    pub fn parse(toml: &str) -> Result<Self, String> {
        let config: RobotConfig = toml::from_str(toml).map_err(|e| e.to_string())?;
        config.validate()?;
        Ok(config)
    }

    /// Checks the rules that the schema cannot express.
    fn validate(&self) -> Result<(), String> {
        let mut errors = Vec::new();
        let mut selectors = BTreeSet::new();
        for (name, camera) in &self.cameras {
            let at = format!("cameras.{name}");
            if name.is_empty()
                || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
            {
                errors.push(format!("{at}: names may only use letters, digits, '-', and '_'"));
            }
            if !selectors.insert((&camera.serial, &camera.port)) {
                errors.push(format!("{at}: another camera has the same serial and port"));
            }
            let shared = self.cameras.values().filter(|c| c.serial == camera.serial).count() > 1;
            if camera.serial.is_empty() {
                errors.push(format!("{at}: serial must not be empty"));
            } else if shared && camera.port.is_none() {
                errors.push(format!(
                    "{at}: serial {:?} is used by several cameras; give each a port",
                    camera.serial
                ));
            }
            if camera.mode.width == 0 || camera.mode.height == 0 || camera.mode.fps == 0 {
                errors.push(format!("{at}.mode: width, height, and fps must be positive"));
            }
            for (key, calibration) in &camera.calibrations {
                let Some((width, height)) = parse_resolution(key) else {
                    errors.push(format!("{at}.calibrations.{key}: keys must be WIDTHxHEIGHT"));
                    continue;
                };
                let valid = [calibration.fx, calibration.fy].iter().all(|f| *f > 0.0)
                    && (0.0..width as f64).contains(&calibration.cx)
                    && (0.0..height as f64).contains(&calibration.cy)
                    && calibration.distortion.iter().all(|k| k.is_finite());
                if !valid {
                    errors.push(format!("{at}.calibrations.{key}: intrinsics are out of range"));
                }
            }
        }
        if errors.is_empty() { Ok(()) } else { Err(errors.join("; ")) }
    }
}

/// Tag poses from a WPILib `AprilTagFieldLayout` JSON file.
#[derive(Debug, Clone, PartialEq)]
pub struct FieldLayout {
    pub tags: BTreeMap<u32, Isometry3<f64>>,
    /// Field length and width in meters, zero when the layout omits them.
    pub size: (f64, f64),
}

/// A field layout for the dashboard's 3D view.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct FieldView {
    /// Meters along +X.
    pub length: f64,
    /// Meters along +Y.
    pub width: f64,
    pub tags: Vec<FieldTag>,
}

/// A tag's field pose: meters, and a quaternion with +X out of the tag's face.
#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct FieldTag {
    pub id: u32,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub qw: f64,
    pub qx: f64,
    pub qy: f64,
    pub qz: f64,
}

impl FieldLayout {
    pub fn parse(json: &str) -> Result<Self, String> {
        #[derive(Deserialize)]
        struct Layout {
            tags: Vec<Tag>,
            #[serde(default)]
            field: Option<Size>,
        }
        #[derive(Deserialize)]
        struct Size {
            length: f64,
            width: f64,
        }
        #[derive(Deserialize)]
        struct Tag {
            #[serde(rename = "ID")]
            id: u32,
            pose: Pose,
        }
        #[derive(Deserialize)]
        struct Pose {
            translation: Xyz,
            rotation: Rotation,
        }
        #[derive(Deserialize)]
        struct Xyz {
            x: f64,
            y: f64,
            z: f64,
        }
        #[derive(Deserialize)]
        struct Rotation {
            quaternion: Wxyz,
        }
        #[derive(Deserialize)]
        #[allow(non_snake_case)]
        struct Wxyz {
            W: f64,
            X: f64,
            Y: f64,
            Z: f64,
        }
        let layout: Layout =
            serde_json::from_str(json).map_err(|e| format!("field layout: {e}"))?;
        let mut tags = BTreeMap::new();
        for tag in layout.tags {
            let t = tag.pose.translation;
            let q = tag.pose.rotation.quaternion;
            let quaternion = Quaternion::new(q.W, q.X, q.Y, q.Z);
            if quaternion.norm().is_nan() || quaternion.norm() == 0.0 {
                return Err(format!("field layout: tag {} has a zero quaternion", tag.id));
            }
            let pose = Isometry3::from_parts(
                Vector3::new(t.x, t.y, t.z).into(),
                UnitQuaternion::from_quaternion(quaternion),
            );
            if tags.insert(tag.id, pose).is_some() {
                return Err(format!("field layout: tag {} is listed twice", tag.id));
            }
        }
        let size = layout.field.map_or((0.0, 0.0), |f| (f.length, f.width));
        Ok(FieldLayout { tags, size })
    }

    pub fn view(&self) -> FieldView {
        let tags = self
            .tags
            .iter()
            .map(|(id, pose)| {
                let t = pose.translation.vector;
                let q = pose.rotation;
                FieldTag { id: *id, x: t.x, y: t.y, z: t.z, qw: q.w, qx: q.i, qy: q.j, qz: q.k }
            })
            .collect();
        FieldView { length: self.size.0, width: self.size.1, tags }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_minimal_camera_with_defaults() {
        let config = RobotConfig::parse(
            r#"
            [cameras.front]
            serial = "A1"
            mount = { x = 0.3, z = 1, pitch = -15 }
            [cameras.front.calibrations.1280x800]
            fx = 900
            fy = 900
            cx = 640
            cy = 400
            distortion = [0, 0, 0, 0, 0]
            "#,
        )
        .unwrap();
        let camera = &config.cameras["front"];
        assert_eq!(camera.mode.to_string(), "1280x800@120");
        assert_eq!(camera.mount.z, 1.0);
        assert!(camera.calibration().is_some());
    }

    #[test]
    fn docs_starter_config_is_valid() {
        RobotConfig::parse(include_str!("../../docs/public/starter/spot.toml")).unwrap();
    }

    #[test]
    fn shared_serials_need_distinct_ports() {
        let error = RobotConfig::parse(
            "[cameras.a]\nserial = \"S\"\nport = \"1-2.1\"\n[cameras.b]\nserial = \"S\"\n\
             [cameras.c]\nserial = \"T\"\nport = \"1-2.3\"\n[cameras.d]\nserial = \"T\"\nport = \"1-2.3\"",
        )
        .unwrap_err();
        assert!(!error.contains("cameras.a"), "{error}");
        assert!(error.contains("cameras.b: serial \"S\" is used by several cameras"), "{error}");
        assert!(
            error.contains("cameras.d: another camera has the same serial and port"),
            "{error}"
        );
    }
}
