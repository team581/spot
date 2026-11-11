//! WPILib struct schemas and packing for Spot's NetworkTables values.

use nalgebra::{Isometry3, UnitQuaternion};

/// Schemas published under `/.schema/struct:<name>`, dependencies first.
pub const SCHEMAS: &[(&str, &str)] = &[
    ("Translation3d", "double x;double y;double z"),
    ("Quaternion", "double w;double x;double y;double z"),
    ("Rotation3d", "Quaternion q"),
    ("Pose3d", "Translation3d translation;Rotation3d rotation"),
    (
        "SpotStatus",
        "char version[16];enum {ready=0, waiting_for_time_sync=1, waiting_for_config=2, \
         invalid_config=3, missing_camera=4, uncalibrated_camera=5} uint8 state;\
         bool overrides_active",
    ),
    (
        "SpotCameraStatus",
        "enum {streaming=0, disconnected=1, duplicate_serial=2, uncalibrated=3, \
         falling_behind=4} uint8 state;double fps;uint32 dropped_frames",
    ),
    (
        "SpotEstimate",
        "Pose3d primary;double primary_error;bool has_alternate;Pose3d alternate;\
         double alternate_error;int64 tag_ids;double average_tag_distance;double tag_area",
    ),
];

#[derive(Default)]
pub struct Writer(pub Vec<u8>);

impl Writer {
    pub fn f64(&mut self, value: f64) -> &mut Self {
        self.0.extend_from_slice(&value.to_le_bytes());
        self
    }
    pub fn u8(&mut self, value: u8) -> &mut Self {
        self.0.push(value);
        self
    }
    pub fn bool(&mut self, value: bool) -> &mut Self {
        self.u8(value as u8)
    }
    pub fn u32(&mut self, value: u32) -> &mut Self {
        self.0.extend_from_slice(&value.to_le_bytes());
        self
    }
    pub fn i64(&mut self, value: i64) -> &mut Self {
        self.0.extend_from_slice(&value.to_le_bytes());
        self
    }
    pub fn chars(&mut self, value: &str, len: usize) -> &mut Self {
        let mut bytes = value.as_bytes().to_vec();
        bytes.resize(len, 0);
        self.0.extend_from_slice(&bytes);
        self
    }
    pub fn pose3d(&mut self, pose: &Isometry3<f64>) -> &mut Self {
        let t = pose.translation.vector;
        let q: &UnitQuaternion<f64> = &pose.rotation;
        self.f64(t.x).f64(t.y).f64(t.z).f64(q.w).f64(q.i).f64(q.j).f64(q.k)
    }
}
