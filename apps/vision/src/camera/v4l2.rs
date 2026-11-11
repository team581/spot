//! UVC cameras through V4L2.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::Context;
use v4l::FourCC;
use v4l::buffer::Type;
use v4l::control::{Control, Value};
use v4l::frameinterval::FrameIntervalEnum;
use v4l::framesize::FrameSizeEnum;
use v4l::io::mmap::Stream;
use v4l::io::traits::CaptureStream;
use v4l::video::Capture;
use v4l::video::capture::Parameters;

use super::{ControlRange, Device, Frame, Source};
use crate::config::{AutoExposure, Controls, Mode};

const MJPG: FourCC = FourCC { repr: *b"MJPG" };
const AUTO_EXPOSURE: u32 = 0x009a_0901;
const EXPOSURE_TIME_ABSOLUTE: u32 = 0x009a_0902;
const GAIN: u32 = 0x0098_0913;
const CONTROLS: [(&str, u32); 3] = [
    ("auto_exposure", AUTO_EXPOSURE),
    ("exposure_time_absolute", EXPOSURE_TIME_ABSOLUTE),
    ("gain", GAIN),
];
/// Symlinks to capture nodes, named by physical port label (from the J401 Nix module).
const PORTS: &str = "/dev/spot";

/// Modes and controls by device node and USB path, which only change on replug.
pub type Cache = HashMap<(String, PathBuf), (Vec<Mode>, Vec<ControlRange>)>;

fn read(path: &Path) -> Option<String> {
    Some(std::fs::read_to_string(path).ok()?.trim().to_string())
}

pub fn devices(cache: &mut Cache) -> Vec<Device> {
    let ports: HashMap<PathBuf, String> = std::fs::read_dir(PORTS)
        .into_iter()
        .flatten()
        .filter_map(|entry| {
            let entry = entry.ok()?;
            Some((
                entry.path().canonicalize().ok()?,
                entry.file_name().to_string_lossy().into_owned(),
            ))
        })
        .collect();
    let Ok(entries) = std::fs::read_dir("/sys/class/video4linux") else { return Vec::new() };
    let mut devices = Vec::new();
    let mut seen = Vec::new();
    for entry in entries.flatten() {
        let sys = entry.path();
        // UVC cameras expose metadata nodes too; index 0 is the capture node.
        if read(&sys.join("index")).as_deref() != Some("0") {
            continue;
        }
        let Some(usb) =
            sys.join("device").canonicalize().ok().and_then(|i| Some(i.parent()?.to_path_buf()))
        else {
            continue;
        };
        let path = format!("/dev/{}", entry.file_name().to_string_lossy());
        let key = (path.clone(), usb.clone());
        seen.push(key.clone());
        if !cache.contains_key(&key) {
            match probe(&path) {
                Ok(probed) => {
                    cache.insert(key.clone(), probed);
                }
                Err(error) => {
                    tracing::debug!(%path, %error, "skipping video device");
                    continue;
                }
            }
        }
        let (modes, controls) = cache[&key].clone();
        devices.push(Device {
            port: ports.get(Path::new(&path)).cloned(),
            serial: read(&usb.join("serial")).filter(|s| !s.is_empty()),
            product: read(&usb.join("product")).unwrap_or_else(|| "USB camera".into()),
            path,
            modes,
            controls,
        });
    }
    cache.retain(|key, _| seen.contains(key));
    devices.sort_by(|a, b| a.path.cmp(&b.path));
    devices
}

fn probe(path: &str) -> anyhow::Result<(Vec<Mode>, Vec<ControlRange>)> {
    let device = v4l::Device::with_path(path)?;
    let mut modes = Vec::new();
    for size in device.enum_framesizes(MJPG)? {
        let FrameSizeEnum::Discrete(size) = size.size else { continue };
        for interval in device.enum_frameintervals(MJPG, size.width, size.height)? {
            if let FrameIntervalEnum::Discrete(fraction) = interval.interval {
                if fraction.numerator > 0 {
                    let fps =
                        (fraction.denominator as f64 / fraction.numerator as f64).round() as u32;
                    modes.push(Mode { width: size.width, height: size.height, fps });
                }
            }
        }
    }
    anyhow::ensure!(!modes.is_empty(), "no MJPEG modes");
    modes.sort();
    modes.dedup();
    let descriptions = device.query_controls().unwrap_or_default();
    let controls = CONTROLS
        .iter()
        .filter_map(|(name, id)| {
            let d = descriptions.iter().find(|d| d.id == *id)?;
            Some(ControlRange {
                name: name.to_string(),
                min: d.minimum,
                max: d.maximum,
                step: d.step as i64,
                default: d.default,
            })
        })
        .collect();
    Ok((modes, controls))
}

struct V4l2 {
    device: v4l::Device,
    stream: Stream<'static>,
    defaults: HashMap<u32, i64>,
}

pub fn open(device: &Device, mode: Mode, controls: &Controls) -> anyhow::Result<Box<dyn Source>> {
    anyhow::ensure!(device.modes.contains(&mode), "mode {mode} is not supported");
    let handle = v4l::Device::with_path(&device.path).with_context(|| device.path.clone())?;
    let mut format = handle.format()?;
    (format.width, format.height, format.fourcc) = (mode.width, mode.height, MJPG);
    let format = handle.set_format(&format)?;
    anyhow::ensure!(
        (format.width, format.height, format.fourcc) == (mode.width, mode.height, MJPG),
        "camera chose {}x{} {} instead of {mode}",
        format.width,
        format.height,
        format.fourcc
    );
    handle.set_params(&Parameters::with_fps(mode.fps))?;
    let defaults = device
        .controls
        .iter()
        .filter_map(|c| Some((CONTROLS.iter().find(|(n, _)| *n == c.name)?.1, c.default)))
        .collect();
    let mut stream = Stream::with_buffers(&handle, Type::VideoCapture, 4)?;
    stream.set_timeout(Duration::from_secs(1));
    let mut source = V4l2 { device: handle, stream, defaults };
    source.apply(controls)?;
    Ok(Box::new(source))
}

impl V4l2 {
    fn set(&self, id: u32, value: Option<i64>) -> anyhow::Result<()> {
        let Some(value) = value.or_else(|| self.defaults.get(&id).copied()) else { return Ok(()) };
        Ok(self.device.set_control(Control { id, value: Value::Integer(value) })?)
    }
}

impl Source for V4l2 {
    fn next(&mut self) -> anyhow::Result<Frame> {
        let (buffer, meta) = self.stream.next()?;
        let monotonic_us = meta.timestamp.sec * 1_000_000 + meta.timestamp.usec;
        Ok(Frame { jpeg: buffer[..meta.bytesused as usize].to_vec(), monotonic_us })
    }

    fn apply(&mut self, controls: &Controls) -> anyhow::Result<()> {
        let auto_exposure = controls.auto_exposure.map(|mode| match mode {
            AutoExposure::Manual => 1,
            AutoExposure::AperturePriority => 3,
        });
        self.set(AUTO_EXPOSURE, auto_exposure).context("auto_exposure")?;
        let manual =
            auto_exposure.or_else(|| self.defaults.get(&AUTO_EXPOSURE).copied()) == Some(1);
        if manual {
            self.set(EXPOSURE_TIME_ABSOLUTE, controls.exposure_time_absolute.map(i64::from))
                .context("exposure_time_absolute")?;
        }
        self.set(GAIN, controls.gain.map(i64::from)).context("gain")
    }
}
