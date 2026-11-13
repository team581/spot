//! Logging for the dashboard: a live WebSocket server and MCAP recordings from a rolling buffer.
//!
//! Everything is logged to one Foxglove SDK context, whose WebSocket server feeds the
//! dashboard's live views. An MCAP writer on that context rotates every few seconds into a
//! buffer directory. Segments around robot enables, or requested with `saveRecording`, are
//! merged into a recording; the rest age out. The dashboard replays recordings.

use std::collections::{BTreeMap, HashMap, VecDeque};
use std::fs::File;
use std::io::BufWriter;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

use foxglove::messages::{CompressedImage, Log, Timestamp};
use foxglove::{
    Channel, Context, McapWriteOptions, McapWriter, McapWriterHandle, RawChannel, Schema,
};
use serde::Serialize;
use serde_json::json;
use utoipa::ToSchema;

use crate::app::Fms;
use crate::clock::monotonic_us;
use crate::config::{FieldLayout, RobotConfig};
use crate::nt::Nt;
use crate::pipeline::FrameResult;

const SEGMENT_US: i64 = 2_000_000;
const PREROLL_US: i64 = 5_000_000;
const POSTROLL_US: i64 = 5_000_000;
/// How far back `saveRecording` can reach.
const BUFFER_US: i64 = 60_000_000;
const ENABLED: i64 = 0x01;
const FMS_ATTACHED: i64 = 0x10;

pub const WEBSOCKET_PORT: u16 = 5801;

struct Segment {
    path: PathBuf,
    start_us: i64,
    end_us: i64,
}

struct Active {
    start_us: i64,
    name: String,
    disabled_us: Option<i64>,
}

struct CameraChannels {
    image: Channel<CompressedImage>,
    detections: Arc<RawChannel>,
    charuco: Arc<RawChannel>,
    last_image_us: Option<i64>,
}

struct State {
    writer: Option<(McapWriterHandle<BufWriter<File>>, PathBuf, i64)>,
    segments: VecDeque<Segment>,
    next_segment: u64,
    active: Option<Active>,
    config: Option<(RobotConfig, Option<Arc<FieldLayout>>)>,
    cameras: HashMap<String, CameraChannels>,
    /// Log times are NT server time while synced and local time otherwise.
    synced: bool,
    last_us: i64,
}

pub struct Recorder {
    /// Log times are NT server time once synced, like WPILOG.
    nt: OnceLock<Arc<Nt>>,
    context: Arc<Context>,
    dir: PathBuf,
    buffer: PathBuf,
    state: Mutex<State>,
    status: Arc<RawChannel>,
    config: Arc<RawChannel>,
    field: Arc<RawChannel>,
    log: Channel<Log>,
}

#[derive(Serialize, ToSchema)]
pub struct Recording {
    /// File name, downloadable from `/recordings/<name>`.
    pub name: String,
    pub bytes: u64,
    /// Unix time the recording was finished, in seconds.
    pub modified: u64,
}

fn json_channel(context: &Arc<Context>, topic: &str, name: &str) -> Arc<RawChannel> {
    context
        .channel_builder(topic)
        .message_encoding("json")
        .schema(Schema::new(name, "jsonschema", br#"{"type":"object"}"#.as_slice()))
        .build_raw()
        .expect("unique topic")
}

fn log_json(channel: &RawChannel, message: &[u8], time: u64) {
    channel.log_with_meta(message, foxglove::PartialMetadata { log_time: Some(time) });
}

fn timestamp(us: i64) -> Option<Timestamp> {
    let us = us.max(0) as u64;
    Some(Timestamp::new((us / 1_000_000) as u32, (us % 1_000_000 * 1_000) as u32))
}

fn nanos(us: i64) -> u64 {
    us.max(0) as u64 * 1_000
}

impl Recorder {
    pub fn new(state_dir: &Path) -> Arc<Self> {
        let dir = state_dir.join("recordings");
        let buffer = dir.join(".buffer");
        // Segments from a previous run have no usable index of times.
        let _ = std::fs::remove_dir_all(&buffer);
        std::fs::create_dir_all(&buffer).expect("recordings directory");
        let context = Context::new();
        Arc::new(Recorder {
            nt: OnceLock::new(),
            status: json_channel(&context, "/spot/status", "spot.Status"),
            config: json_channel(&context, "/spot/config", "spot.Config"),
            field: json_channel(&context, "/spot/field", "spot.Field"),
            log: context.channel_builder("/log").build(),
            context,
            dir,
            buffer,
            state: Mutex::new(State {
                writer: None,
                segments: VecDeque::new(),
                next_segment: 0,
                active: None,
                config: None,
                cameras: HashMap::new(),
                synced: false,
                last_us: 0,
            }),
        })
    }

    pub fn set_clock(&self, nt: Arc<Nt>) {
        let _ = self.nt.set(nt);
    }

    /// NT server time when synced, otherwise local monotonic time.
    pub fn log_time(&self, monotonic_us: i64) -> i64 {
        self.nt.get().and_then(|nt| nt.server_time_us(monotonic_us)).unwrap_or(monotonic_us)
    }

    fn now(&self) -> i64 {
        self.log_time(monotonic_us())
    }

    pub async fn serve(&self) -> anyhow::Result<()> {
        foxglove::WebSocketServer::new()
            .name("Spot")
            .context(&self.context)
            .bind("0.0.0.0", WEBSOCKET_PORT)
            .start()
            .await?;
        Ok(())
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    /// Records the effective config and field layout.
    pub fn set_config(&self, config: &RobotConfig, layout: Option<Arc<FieldLayout>>) {
        let mut state = self.state.lock().unwrap();
        state.config = Some((config.clone(), layout));
        self.log_latched(&mut state, self.now());
    }

    /// Logs messages that every segment must start with.
    fn log_latched(&self, state: &mut State, now_us: i64) {
        let Some((config, layout)) = &state.config else { return };
        let time = nanos(now_us);
        log_json(&self.config, &serde_json::to_vec(config).unwrap(), time);
        if let Some(layout) = layout {
            log_json(&self.field, &serde_json::to_vec(&layout.view()).unwrap(), time);
        }
    }

    fn camera<'a>(&self, state: &'a mut State, name: &str) -> &'a mut CameraChannels {
        state.cameras.entry(name.to_string()).or_insert_with(|| CameraChannels {
            image: self.context.channel_builder(format!("/{name}/image")).build(),
            detections: json_channel(
                &self.context,
                &format!("/{name}/detections"),
                "spot.Detections",
            ),
            charuco: json_channel(&self.context, &format!("/{name}/charuco"), "spot.Charuco"),
            last_image_us: None,
        })
    }

    /// Logs a processed frame: detections every frame, images at the configured rate.
    pub fn frame(&self, result: &FrameResult) {
        let time_us = self.log_time(result.monotonic_us);
        let mut state = self.state.lock().unwrap();
        let image_fps = state.config.as_ref().map_or(30.0, |(c, _)| c.recording.image_fps);
        let channels = self.camera(&mut state, result.camera);
        let time = nanos(time_us);
        let tags: Vec<_> = result
            .detections
            .iter()
            .map(|d| {
                json!({
                    "id": d.id,
                    "corners": d.corners,
                    "hamming": d.hamming,
                    "decision_margin": d.decision_margin,
                    "used": result.used_tags.contains(&d.id),
                })
            })
            .collect();
        let candidate = |c: &crate::pose::Candidate| {
            let t = c.pose.translation.vector;
            let (roll, pitch, yaw) = c.pose.rotation.euler_angles();
            json!({
                "x": t.x,
                "y": t.y,
                "z": t.z,
                "roll": roll.to_degrees(),
                "pitch": pitch.to_degrees(),
                "yaw": yaw.to_degrees(),
                "error": c.error,
            })
        };
        let estimate = result.estimate.as_ref().map(|e| {
            json!({
                "primary": candidate(&e.primary),
                "alternate": e.alternate.as_ref().map(candidate),
                "average_tag_distance": e.average_tag_distance,
                "tag_area": e.tag_area,
            })
        });
        let message = json!({ "width": result.width, "height": result.height, "tags": tags, "estimate": estimate });
        log_json(&channels.detections, &serde_json::to_vec(&message).unwrap(), time);

        let due = channels
            .last_image_us
            .is_none_or(|last| (time_us - last) as f64 >= 1e6 / image_fps * 0.9);
        if image_fps > 0.0 && due {
            channels.last_image_us = Some(time_us);
            channels.image.log_with_time(
                &CompressedImage {
                    timestamp: timestamp(time_us),
                    frame_id: result.camera.to_string(),
                    data: result.jpeg.to_vec().into(),
                    format: "jpeg".into(),
                },
                time,
            );
        }

        if let Some(view) = &result.charuco {
            let message = json!({
                "width": result.width,
                "height": result.height,
                "ids": view.ids,
                "corners": view.corners,
            });
            log_json(&channels.charuco, &serde_json::to_vec(&message).unwrap(), time);
        }
    }

    pub fn status<T: Serialize>(&self, status: &T) {
        log_json(&self.status, &serde_json::to_vec(status).unwrap(), nanos(self.now()));
    }

    pub fn log(&self, mut log: Log) {
        let now = self.now();
        log.timestamp = timestamp(now);
        self.log.log_with_time(&log, nanos(now));
    }

    /// Rotates segments and starts or finishes enable-triggered recordings.
    pub fn tick(&self, fms: &Fms) {
        let synced = self.nt.get().is_some_and(|nt| nt.synced());
        let now_us = self.now();
        let mut state = self.state.lock().unwrap();
        if synced != state.synced {
            // Log times jump to another time base. Finish with the old one and start over.
            let end_us = state.last_us;
            if let Some(active) = state.active.take() {
                self.finish(&mut state, active.start_us, end_us, active.name);
            }
            self.close_segment(&mut state, end_us);
            for segment in state.segments.drain(..) {
                let _ = std::fs::remove_file(segment.path);
            }
            state.synced = synced;
        }
        state.last_us = now_us;
        let recording = state.config.as_ref().is_some_and(|(c, _)| c.recording.enabled);
        if !recording {
            self.close_segment(&mut state, now_us);
            state.active = None;
        } else if state.writer.as_ref().is_none_or(|(_, _, start)| now_us - start >= SEGMENT_US) {
            self.rotate(&mut state, now_us);
        }

        let robot_enabled = recording && synced && fms.control & ENABLED != 0;
        match &mut state.active {
            None if robot_enabled => {
                state.active = Some(Active {
                    start_us: now_us - PREROLL_US,
                    name: name(fms),
                    disabled_us: None,
                });
            }
            Some(active) if robot_enabled => active.disabled_us = None,
            Some(active) if active.disabled_us.is_none() => active.disabled_us = Some(now_us),
            Some(Active { disabled_us: Some(at), .. }) if now_us - *at >= POSTROLL_US => {
                let active = state.active.take().unwrap();
                self.finish(&mut state, active.start_us, now_us, active.name);
            }
            _ => {}
        }

        let keep_from = state
            .active
            .as_ref()
            .map_or(now_us - BUFFER_US, |a| a.start_us.min(now_us - BUFFER_US));
        while state.segments.front().is_some_and(|s| s.end_us < keep_from) {
            let segment = state.segments.pop_front().unwrap();
            let _ = std::fs::remove_file(segment.path);
        }
    }

    /// Saves the last `seconds` of the buffer as a recording.
    pub fn save(&self, seconds: f64) {
        let now_us = self.now();
        let mut state = self.state.lock().unwrap();
        let start = now_us - (seconds.clamp(0.0, BUFFER_US as f64 / 1e6) * 1e6) as i64;
        self.finish(&mut state, start, now_us, format!("{}_saved", local_time()));
    }

    fn close_segment(&self, state: &mut State, now_us: i64) {
        if let Some((writer, path, start_us)) = state.writer.take() {
            match writer.close() {
                Ok(_) => state.segments.push_back(Segment { path, start_us, end_us: now_us }),
                Err(error) => tracing::error!(%error, "could not finish recording segment"),
            }
        }
    }

    fn rotate(&self, state: &mut State, now_us: i64) {
        self.close_segment(state, now_us);
        let path = self.buffer.join(format!("{:08}.mcap", state.next_segment));
        state.next_segment += 1;
        // JPEGs dominate and do not compress.
        let writer = McapWriter::with_options(McapWriteOptions::new().compression(None));
        match writer.context(&self.context).create_new_buffered_file(&path) {
            Ok(writer) => {
                state.writer = Some((writer, path, now_us));
                self.log_latched(state, now_us);
            }
            Err(error) => tracing::error!(%error, "could not start recording segment"),
        }
    }

    /// Merges the segments overlapping `start_us..end_us` into a recording in the background.
    fn finish(&self, state: &mut State, start_us: i64, end_us: i64, name: String) {
        self.close_segment(state, end_us);
        let staging = self.buffer.join(format!("merge-{name}"));
        let _ = std::fs::create_dir_all(&staging);
        // Hard links keep segments alive while the buffer moves on.
        let inputs: Vec<PathBuf> = state
            .segments
            .iter()
            .filter(|s| s.end_us >= start_us && s.start_us <= end_us)
            .filter_map(|s| {
                let link = staging.join(s.path.file_name()?);
                std::fs::hard_link(&s.path, &link).ok().map(|()| link)
            })
            .collect();
        if inputs.is_empty() {
            let _ = std::fs::remove_dir_all(staging);
            return;
        }
        let mut output = self.dir.join(format!("{name}.mcap"));
        for n in 2.. {
            if !output.exists() {
                break;
            }
            output = self.dir.join(format!("{name}_{n}.mcap"));
        }
        let limit = state.config.as_ref().map_or(80.0, |(c, _)| c.recording.max_disk_usage_percent);
        let dir = self.dir.clone();
        std::thread::spawn(move || {
            match merge(&inputs, &output, nanos(start_us), nanos(end_us)) {
                Ok(()) => tracing::info!(recording = %output.display(), "saved recording"),
                Err(error) => tracing::error!(%error, "could not save recording"),
            }
            let _ = std::fs::remove_dir_all(staging);
            prune(&dir, limit);
        });
        self.rotate(state, end_us);
    }

    pub fn recordings(&self) -> Vec<Recording> {
        let mut recordings: Vec<Recording> = std::fs::read_dir(&self.dir)
            .into_iter()
            .flatten()
            .filter_map(|entry| {
                let entry = entry.ok()?;
                let name = entry.file_name().into_string().ok()?;
                let metadata = entry.metadata().ok()?;
                (name.ends_with(".mcap") && metadata.is_file()).then(|| Recording {
                    name,
                    bytes: metadata.len(),
                    modified: metadata
                        .modified()
                        .ok()
                        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                        .map_or(0, |d| d.as_secs()),
                })
            })
            .collect();
        recordings.sort_by_key(|r| std::cmp::Reverse(r.modified));
        recordings
    }
}

/// `EVENT_Q12` when the FMS is attached, otherwise the local time.
fn name(fms: &Fms) -> String {
    let kind = match fms.match_type {
        1 => "P",
        2 => "Q",
        3 => "E",
        _ => "",
    };
    if fms.control & FMS_ATTACHED != 0 && !fms.event.is_empty() && !kind.is_empty() {
        let event: String =
            fms.event.chars().filter(|c| c.is_ascii_alphanumeric() || *c == '-').collect();
        let replay = if fms.replay > 1 { format!("_R{}", fms.replay) } else { String::new() };
        format!("{event}_{kind}{}{replay}", fms.match_number)
    } else {
        local_time()
    }
}

fn local_time() -> String {
    // SAFETY: `time` accepts null, and `tm` is written by localtime_r before it is read.
    let tm = unsafe {
        let now = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&now, &mut tm);
        tm
    };
    format!(
        "{:04}-{:02}-{:02}_{:02}-{:02}-{:02}",
        tm.tm_year + 1900,
        tm.tm_mon + 1,
        tm.tm_mday,
        tm.tm_hour,
        tm.tm_min,
        tm.tm_sec
    )
}

/// Topics that are logged at the start of each segment and needed from the start of a recording.
const LATCHED: &[&str] = &["/spot/config", "/spot/field"];

/// Writes everything but images first, so a replay can load those small chunks without reading
/// the images. Latched messages from before `start` are kept.
fn merge(inputs: &[PathBuf], output: &Path, start: u64, end: u64) -> anyhow::Result<()> {
    let temporary = output.with_extension("mcap.tmp");
    let mut writer = mcap::WriteOptions::new()
        .compression(None)
        .create(BufWriter::new(File::create(&temporary)?))?;
    let mut schemas: HashMap<(String, Vec<u8>), u16> = HashMap::new();
    let mut channels: HashMap<(String, u16), u16> = HashMap::new();
    let mut sequence = 0;
    let inputs = inputs.iter().map(std::fs::read).collect::<Result<Vec<_>, _>>()?;
    for images in [false, true] {
        for bytes in &inputs {
            for message in mcap::MessageStream::new(bytes)? {
                let Ok(message) = message else { break };
                let image = message.channel.topic.ends_with("/image");
                let wanted = (start..=end).contains(&message.log_time)
                    || (message.log_time < start && LATCHED.contains(&&*message.channel.topic));
                if image != images || !wanted {
                    continue;
                }
                let schema_id = match &message.channel.schema {
                    Some(schema) => {
                        let key = (schema.name.clone(), schema.data.to_vec());
                        match schemas.get(&key) {
                            Some(id) => *id,
                            None => {
                                let id = writer.add_schema(
                                    &schema.name,
                                    &schema.encoding,
                                    &schema.data,
                                )?;
                                schemas.insert(key, id);
                                id
                            }
                        }
                    }
                    None => 0,
                };
                let key = (message.channel.topic.clone(), schema_id);
                let channel_id = match channels.get(&key) {
                    Some(id) => *id,
                    None => {
                        let id = writer.add_channel(
                            schema_id,
                            &message.channel.topic,
                            &message.channel.message_encoding,
                            &BTreeMap::new(),
                        )?;
                        channels.insert(key, id);
                        id
                    }
                };
                sequence += 1;
                writer.write_to_known_channel(
                    &mcap::records::MessageHeader {
                        channel_id,
                        sequence,
                        log_time: message.log_time,
                        publish_time: message.publish_time,
                    },
                    &message.data,
                )?;
            }
        }
        // Ends the chunk so images start in their own.
        writer.flush()?;
    }
    writer.finish()?;
    drop(writer);
    std::fs::rename(temporary, output)?;
    Ok(())
}

/// Deletes the oldest recordings while the disk is fuller than `limit` percent.
fn prune(dir: &Path, limit: f64) {
    let usage = || crate::system::disk_percent(dir);
    let mut files: Vec<(std::time::SystemTime, PathBuf)> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .filter_map(|e| {
            let e = e.ok()?;
            let path = e.path();
            (path.extension()? == "mcap").then_some(())?;
            Some((e.metadata().ok()?.modified().ok()?, path))
        })
        .collect();
    files.sort();
    for (_, path) in files {
        if usage().is_none_or(|u| u <= limit) {
            break;
        }
        tracing::info!(recording = %path.display(), "deleting old recording to free space");
        let _ = std::fs::remove_file(path);
    }
}

/// Forwards service logs to the `/log` channel.
pub struct LogLayer(pub Arc<Recorder>);

impl<S: tracing::Subscriber> tracing_subscriber::Layer<S> for LogLayer {
    fn on_event(&self, event: &tracing::Event<'_>, _: tracing_subscriber::layer::Context<'_, S>) {
        thread_local!(static LOGGING: std::cell::Cell<bool> = const { std::cell::Cell::new(false) });
        // Logging can itself emit events; never recurse.
        if LOGGING.replace(true) {
            return;
        }
        struct Fields(String);
        impl tracing::field::Visit for Fields {
            fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn std::fmt::Debug) {
                use std::fmt::Write;
                let separator = if self.0.is_empty() { "" } else { " " };
                let _ = match field.name() {
                    "message" => write!(self.0, "{separator}{value:?}"),
                    name => write!(self.0, "{separator}{name}={value:?}"),
                };
            }
        }
        let mut fields = Fields(String::new());
        event.record(&mut fields);
        let metadata = event.metadata();
        let level = match *metadata.level() {
            tracing::Level::ERROR => 4,
            tracing::Level::WARN => 3,
            tracing::Level::INFO => 2,
            _ => 1,
        };
        self.0.log(Log {
            timestamp: None,
            level,
            message: fields.0,
            name: metadata.target().to_string(),
            file: metadata.file().unwrap_or_default().to_string(),
            line: metadata.line().unwrap_or_default(),
        });
        LOGGING.set(false);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn segment(path: &Path, messages: &[(&str, u64)]) {
        let mut writer = mcap::Writer::new(BufWriter::new(File::create(path).unwrap())).unwrap();
        let mut channels = HashMap::new();
        for (topic, time) in messages {
            let channel = *channels
                .entry(*topic)
                .or_insert_with(|| writer.add_channel(0, topic, "json", &BTreeMap::new()).unwrap());
            let header = mcap::records::MessageHeader {
                channel_id: channel,
                sequence: 0,
                log_time: *time,
                publish_time: *time,
            };
            writer.write_to_known_channel(&header, b"{}").unwrap();
        }
        writer.finish().unwrap();
    }

    #[test]
    fn merge_keeps_latched_messages_and_writes_images_last() {
        let dir = std::env::temp_dir().join(format!("spot-merge-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let (a, b, output) = (dir.join("a.mcap"), dir.join("b.mcap"), dir.join("out.mcap"));
        segment(
            &a,
            &[("/spot/config", 0), ("/c/image", 5), ("/c/detections", 5), ("/c/detections", 15)],
        );
        segment(
            &b,
            &[("/spot/config", 20), ("/c/image", 25), ("/c/detections", 25), ("/c/detections", 40)],
        );

        merge(&[a, b], &output, 10, 30).unwrap();

        let bytes = std::fs::read(&output).unwrap();
        let messages: Vec<_> = mcap::MessageStream::new(&bytes)
            .unwrap()
            .map(|m| m.map(|m| (m.channel.topic.clone(), m.log_time)).unwrap())
            .collect();
        let expected = [
            ("/spot/config", 0),
            ("/c/detections", 15),
            ("/spot/config", 20),
            ("/c/detections", 25),
            ("/c/image", 25),
        ];
        assert_eq!(messages, expected.map(|(topic, time)| (topic.to_string(), time)));
        let _ = std::fs::remove_dir_all(dir);
    }
}
