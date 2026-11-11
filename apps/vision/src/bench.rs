//! `spot-vision bench`: per-stage processing times on JPEG files.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use anyhow::Context;

use crate::config::{FieldLayout, RobotConfig};
use crate::decode::Decoder;
use crate::detect::Detector;
use crate::pipeline::{self, Processing};

#[derive(clap::Args)]
pub struct Bench {
    /// Robot config TOML. Its first camera's mount and the calibration for each image's
    /// resolution are used to time pose solving.
    #[arg(long, requires = "layout")]
    config: Option<PathBuf>,
    /// WPILib field layout JSON.
    #[arg(long, requires = "config")]
    layout: Option<PathBuf>,
    /// Frames to process per image and camera.
    #[arg(long, default_value_t = 200)]
    iterations: usize,
    /// Cameras processing at once, each with its own decoder and detector.
    #[arg(long, default_value_t = 1)]
    cameras: usize,
    images: Vec<PathBuf>,
}

/// Milliseconds for decode, detect, pose, and the whole frame.
type Sample = [f64; 4];

fn processing(config: &RobotConfig, layout: &Arc<FieldLayout>, size: (u32, u32)) -> Processing {
    let camera = config.cameras.values().next();
    let resolution = format!("{}x{}", size.0, size.1);
    Processing {
        calibration: camera.and_then(|c| c.calibrations.get(&resolution).cloned()),
        mount: camera.map(|c| c.mount.isometry()).unwrap_or_default(),
        tag_size: config.tag_size,
        ignored_tags: config.ignored_tags.clone(),
        layout: Some(layout.clone()),
        charuco: None,
    }
}

fn run(
    jpeg: &[u8],
    setup: Option<&(RobotConfig, Arc<FieldLayout>)>,
    iterations: usize,
) -> anyhow::Result<(Vec<Sample>, usize, bool)> {
    let mut decoder = Decoder::new()?;
    let size = crate::decode::dimensions(jpeg)?;
    let processing = setup.map(|(config, layout)| processing(config, layout, size));
    let calibration = processing.as_ref().and_then(|p| p.calibration.as_ref());
    let mut detector = Detector::new(size.0, size.1, calibration)?;
    let mut samples = Vec::with_capacity(iterations);
    let (mut tags, mut solved) = (0, false);
    // The first frames warm up allocations and GPU kernels.
    for i in 0..iterations + 5 {
        let start = Instant::now();
        let gray = decoder.decode(jpeg)?;
        let decoded = Instant::now();
        let detections = detector.detect(&gray.pixels)?;
        let detected = Instant::now();
        let estimate = processing.as_ref().and_then(|p| pipeline::estimate(p, &detections, size).1);
        let done = Instant::now();
        let ms = |a: Instant, b: Instant| (b - a).as_secs_f64() * 1e3;
        tags = detections.len();
        solved = estimate.is_some();
        if i >= 5 {
            samples.push([
                ms(start, decoded),
                ms(decoded, detected),
                ms(detected, done),
                ms(start, done),
            ]);
        }
    }
    Ok((samples, tags, solved))
}

fn percentile(samples: &[Sample], stage: usize, p: f64) -> f64 {
    let mut values: Vec<f64> = samples.iter().map(|s| s[stage]).collect();
    values.sort_by(f64::total_cmp);
    values[((values.len() - 1) as f64 * p).round() as usize]
}

fn name(path: &Path) -> String {
    path.file_name().map_or_else(String::new, |n| n.to_string_lossy().into_owned())
}

impl Bench {
    pub fn run(self) -> anyhow::Result<()> {
        let setup = match (&self.config, &self.layout) {
            (Some(config), Some(layout)) => Some(Arc::new((
                RobotConfig::parse(&std::fs::read_to_string(config)?)
                    .map_err(anyhow::Error::msg)?,
                Arc::new(
                    FieldLayout::parse(&std::fs::read_to_string(layout)?)
                        .map_err(anyhow::Error::msg)?,
                ),
            ))),
            _ => None,
        };
        println!(
            "{} camera(s), {} frames each; milliseconds p50 / p95\n{:<28} {:>4} {:>13} {:>13} {:>13} {:>13} {:>9}",
            self.cameras,
            self.iterations,
            "image",
            "tags",
            "decode",
            "detect",
            "pose",
            "frame",
            "fps/cam"
        );
        for path in &self.images {
            let jpeg = Arc::new(std::fs::read(path).with_context(|| path.display().to_string())?);
            let start = Instant::now();
            let results: Vec<_> = std::thread::scope(|scope| {
                let workers: Vec<_> = (0..self.cameras)
                    .map(|_| {
                        let (jpeg, setup) = (jpeg.clone(), setup.clone());
                        scope.spawn(move || run(&jpeg, setup.as_deref(), self.iterations))
                    })
                    .collect();
                workers.into_iter().map(|w| w.join().unwrap()).collect()
            });
            let elapsed = start.elapsed().as_secs_f64();
            let mut samples = Vec::new();
            let (mut tags, mut solved) = (0, false);
            for result in results {
                let (s, t, p) = result?;
                samples.extend(s);
                (tags, solved) = (t, p);
            }
            let stat = |stage| {
                format!(
                    "{:5.2} / {:5.2}",
                    percentile(&samples, stage, 0.5),
                    percentile(&samples, stage, 0.95)
                )
            };
            println!(
                "{:<28} {:>4} {:>13} {:>13} {:>13} {:>13} {:>9.1}",
                name(path),
                tags,
                stat(0),
                stat(1),
                if solved { stat(2) } else { "—".into() },
                stat(3),
                (self.iterations + 5) as f64 / elapsed,
            );
        }
        Ok(())
    }
}
