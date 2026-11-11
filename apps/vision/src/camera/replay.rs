//! Development cameras that repeat a JPEG file at 30 FPS. Each `*.jpg` in the replay folder
//! is one camera whose serial is the file name without its extension.

use std::path::Path;
use std::time::{Duration, Instant};

use anyhow::Context;

use super::{Device, Frame, Source};
use crate::clock::monotonic_us;
use crate::config::{Controls, Mode};

const FPS: u32 = 30;

pub fn devices(dir: &Path) -> Vec<Device> {
    let Ok(entries) = std::fs::read_dir(dir) else { return Vec::new() };
    let mut devices: Vec<Device> = entries
        .filter_map(|entry| {
            let path = entry.ok()?.path();
            if path.extension()? != "jpg" {
                return None;
            }
            let jpeg = std::fs::read(&path).ok()?;
            let (width, height) = crate::decode::dimensions(&jpeg).ok()?;
            Some(Device {
                path: path.to_string_lossy().into_owned(),
                serial: Some(path.file_stem()?.to_string_lossy().into_owned()),
                port: None,
                product: "Replay".into(),
                modes: vec![Mode { width, height, fps: FPS }],
                controls: Vec::new(),
            })
        })
        .collect();
    devices.sort_by(|a, b| a.path.cmp(&b.path));
    devices
}

struct Replay {
    jpeg: Vec<u8>,
    next: Instant,
}

pub fn open(device: &Device, mode: Mode, _: &Controls) -> anyhow::Result<Box<dyn Source>> {
    anyhow::ensure!(device.modes.contains(&mode), "mode {mode} is not supported");
    let jpeg = std::fs::read(&device.path).with_context(|| device.path.clone())?;
    Ok(Box::new(Replay { jpeg, next: Instant::now() }))
}

impl Source for Replay {
    fn next(&mut self) -> anyhow::Result<Frame> {
        std::thread::sleep(self.next.saturating_duration_since(Instant::now()));
        self.next += Duration::from_secs(1) / FPS;
        Ok(Frame { jpeg: self.jpeg.clone(), monotonic_us: monotonic_us() })
    }

    fn apply(&mut self, _: &Controls) -> anyhow::Result<()> {
        Ok(())
    }
}
