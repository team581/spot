//! WPILib struct schemas and packing for Spot's NetworkTables values.

use nalgebra::{Isometry3, UnitQuaternion, Vector3};

use crate::health::{CameraStatus, SpotState};
use crate::pose::Estimate;

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

pub fn spot_status(version: &str, state: SpotState, overrides_active: bool) -> Vec<u8> {
    let mut w = Writer::default();
    w.chars(version, 16).u8(state as u8).bool(overrides_active);
    w.0
}

pub fn spot_camera_status(status: &CameraStatus) -> Vec<u8> {
    let mut w = Writer::default();
    w.u8(status.state as u8).f64(status.fps).u32(status.dropped_frames as u32);
    w.0
}

pub fn spot_estimate(estimate: &Estimate) -> Vec<u8> {
    let mut w = Writer::default();
    let alternate = estimate.alternate.as_ref();
    pose3d(&mut w, &estimate.primary.pose);
    w.f64(estimate.primary.error).bool(alternate.is_some());
    pose3d(&mut w, &alternate.map(|a| a.pose).unwrap_or_default());
    w.f64(alternate.map_or(0.0, |a| a.error))
        .i64(estimate.tag_ids)
        .f64(estimate.average_tag_distance)
        .f64(estimate.tag_area);
    w.0
}

fn pose3d(w: &mut Writer, pose: &Isometry3<f64>) {
    translation3d(w, &pose.translation.vector);
    rotation3d(w, &pose.rotation);
}

fn translation3d(w: &mut Writer, t: &Vector3<f64>) {
    w.f64(t.x).f64(t.y).f64(t.z);
}

fn rotation3d(w: &mut Writer, rotation: &UnitQuaternion<f64>) {
    quaternion(w, rotation);
}

fn quaternion(w: &mut Writer, q: &UnitQuaternion<f64>) {
    w.f64(q.w).f64(q.i).f64(q.j).f64(q.k);
}

#[derive(Default)]
struct Writer(Vec<u8>);

impl Writer {
    fn f64(&mut self, value: f64) -> &mut Self {
        self.0.extend_from_slice(&value.to_le_bytes());
        self
    }
    fn u8(&mut self, value: u8) -> &mut Self {
        self.0.push(value);
        self
    }
    fn bool(&mut self, value: bool) -> &mut Self {
        self.u8(value as u8)
    }
    fn u32(&mut self, value: u32) -> &mut Self {
        self.0.extend_from_slice(&value.to_le_bytes());
        self
    }
    fn i64(&mut self, value: i64) -> &mut Self {
        self.0.extend_from_slice(&value.to_le_bytes());
        self
    }
    fn chars(&mut self, value: &str, len: usize) -> &mut Self {
        let mut bytes = value.as_bytes().to_vec();
        bytes.resize(len, 0);
        self.0.extend_from_slice(&bytes);
        self
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use nalgebra::{Translation3, Vector3};
    use serde_json::{Value, json};

    use super::*;
    use crate::config::Mode;
    use crate::health::CameraState;
    use crate::pose::Candidate;

    /// Decodes packed bytes with a schema from `SCHEMAS`, as robot code does, into fields by
    /// dotted path. Enum fields decode to their names.
    fn decode(name: &str, bytes: &[u8]) -> BTreeMap<String, Value> {
        let mut fields = BTreeMap::new();
        let size = decode_into(name, bytes, "", &mut fields);
        assert_eq!(size, bytes.len(), "{name} is packed to its schema's size");
        fields
    }

    fn decode_into(
        name: &str,
        bytes: &[u8],
        prefix: &str,
        fields: &mut BTreeMap<String, Value>,
    ) -> usize {
        let schema = SCHEMAS.iter().find(|(n, _)| *n == name).unwrap().1;
        let mut offset = 0;
        for declaration in schema.split(';') {
            let (values, declaration) = match declaration.strip_prefix("enum {") {
                Some(rest) => {
                    let (values, rest) = rest.split_once('}').unwrap();
                    (Some(values), rest.trim())
                }
                None => (None, declaration),
            };
            let (kind, field) = declaration.split_once(' ').unwrap();
            let (field, count) = match field.split_once('[') {
                Some((field, count)) => (field, count.trim_end_matches(']').parse().unwrap()),
                None => (field, 1),
            };
            let path = format!("{prefix}{field}");
            let size = match kind {
                "double" | "int64" => 8,
                "uint32" => 4,
                "uint8" | "bool" => 1,
                "char" => count,
                _ => {
                    offset += decode_into(kind, &bytes[offset..], &format!("{path}."), fields);
                    continue;
                }
            };
            let raw = &bytes[offset..offset + size];
            offset += size;
            let value = match kind {
                "double" => json!(f64::from_le_bytes(raw.try_into().unwrap())),
                "int64" => json!(i64::from_le_bytes(raw.try_into().unwrap())),
                "uint32" => json!(u32::from_le_bytes(raw.try_into().unwrap())),
                "bool" => json!(raw[0] != 0),
                "char" => json!(String::from_utf8(raw.to_vec()).unwrap().trim_end_matches('\0')),
                _ => json!(raw[0]),
            };
            let value = match values {
                Some(values) => {
                    let name = values.split(',').find_map(|v| {
                        let (name, number) = v.trim().split_once('=')?;
                        (json!(number.parse::<u8>().ok()?) == value).then_some(name)
                    });
                    json!(name.unwrap_or_else(|| panic!("{path} = {value} is not in the schema")))
                }
                None => value,
            };
            fields.insert(path, value);
        }
        offset
    }

    fn spot_states() -> Vec<SpotState> {
        use SpotState::*;
        let all = vec![
            Ready,
            WaitingForTimeSync,
            WaitingForConfig,
            InvalidConfig,
            MissingCamera,
            UncalibratedCamera,
        ];
        // List a new state above, and in the schema, to make this match compile.
        for state in &all {
            match state {
                Ready | WaitingForTimeSync | WaitingForConfig | InvalidConfig | MissingCamera
                | UncalibratedCamera => {}
            }
        }
        all
    }

    fn camera_states() -> Vec<CameraState> {
        use CameraState::*;
        let all = vec![Streaming, Disconnected, DuplicateSerial, Uncalibrated, FallingBehind];
        // List a new state above, and in the schema, to make this match compile.
        for state in &all {
            match state {
                Streaming | Disconnected | DuplicateSerial | Uncalibrated | FallingBehind => {}
            }
        }
        all
    }

    #[test]
    fn spot_status_matches_its_schema() {
        for state in spot_states() {
            let fields = decode("SpotStatus", &spot_status("2026.0.0", state, true));
            assert_eq!(fields["version"], "2026.0.0");
            assert_eq!(fields["state"], serde_json::to_value(state).unwrap());
            assert_eq!(fields["overrides_active"], true);
        }
    }

    #[test]
    fn camera_status_matches_its_schema() {
        for state in camera_states() {
            let status = CameraStatus {
                name: "front".into(),
                state,
                required: true,
                mode: Mode { width: 1280, height: 800, fps: 120 },
                calibrated: true,
                device: None,
                fps: 118.5,
                capture_fps: 120.0,
                dropped_frames: 3_000_000_000,
                error: None,
            };
            let fields = decode("SpotCameraStatus", &spot_camera_status(&status));
            assert_eq!(fields["state"], serde_json::to_value(state).unwrap());
            assert_eq!(fields["fps"], 118.5);
            assert_eq!(fields["dropped_frames"], 3_000_000_000u32);
        }
    }

    #[test]
    fn estimate_matches_its_schema() {
        let pose = |x, yaw: f64| {
            Isometry3::from_parts(
                Translation3::new(x, 2.0, 0.1),
                UnitQuaternion::from_axis_angle(&Vector3::z_axis(), yaw),
            )
        };
        let mut estimate = Estimate {
            primary: Candidate { pose: pose(1.0, 0.0), error: 0.4 },
            alternate: Some(Candidate { pose: pose(5.0, std::f64::consts::PI), error: 0.9 }),
            tag_ids: 1 << 7 | 1 << 12,
            average_tag_distance: 3.5,
            tag_area: 0.02,
        };
        let fields = decode("SpotEstimate", &spot_estimate(&estimate));
        assert_eq!(fields["primary.translation.x"], 1.0);
        assert_eq!(fields["primary.rotation.q.w"], 1.0);
        assert_eq!(fields["primary_error"], 0.4);
        assert_eq!(fields["has_alternate"], true);
        assert_eq!(fields["alternate.translation.x"], 5.0);
        assert_eq!(fields["alternate.rotation.q.z"], 1.0);
        assert_eq!(fields["alternate_error"], 0.9);
        assert_eq!(fields["tag_ids"], 1 << 7 | 1 << 12);
        assert_eq!(fields["average_tag_distance"], 3.5);
        assert_eq!(fields["tag_area"], 0.02);

        estimate.alternate = None;
        let fields = decode("SpotEstimate", &spot_estimate(&estimate));
        assert_eq!(fields["has_alternate"], false);
        assert_eq!(fields["alternate_error"], 0.0);
    }
}
