//! `spot-vision bench`: per-stage processing times on JPEG files.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use anyhow::Context;

use crate::config::{FieldLayout, Mode, RobotConfig};
use crate::processor::{Processing, Processor};

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

fn processing(
    config: &RobotConfig,
    layout: &Arc<FieldLayout>,
    size: (u32, u32),
) -> anyhow::Result<Processing> {
    let mut camera = config.cameras.values().next().context("the config has no cameras")?.clone();
    camera.mode = Mode { width: size.0, height: size.1, ..camera.mode };
    Ok(Processing::new(&camera, config, Some(layout.clone())))
}

fn run(
    jpeg: &[u8],
    setup: Option<&(RobotConfig, Arc<FieldLayout>)>,
    iterations: usize,
) -> anyhow::Result<(Vec<Sample>, usize, bool)> {
    let size = crate::decode::dimensions(jpeg)?;
    let processing = match setup {
        Some((config, layout)) => processing(config, layout, size)?,
        None => Processing {
            calibration: None,
            mount: Default::default(),
            tag_size: crate::pose::TAG_SIZE,
            ignored_tags: Vec::new(),
            layout: None,
            charuco: None,
        },
    };
    let mut processor = Processor::default();
    let mut samples = Vec::with_capacity(iterations);
    let (mut tags, mut solved) = (0, false);
    // The first frames warm up allocations and GPU kernels.
    for i in 0..iterations + 5 {
        let start = Instant::now();
        let processed = processor.process(jpeg, &processing)?;
        let frame = start.elapsed();
        let ms = |d: std::time::Duration| d.as_secs_f64() * 1e3;
        tags = processed.detections.len();
        solved = processed.estimate.is_some();
        if i >= 5 {
            let t = &processed.timings;
            samples.push([ms(t.decode), ms(t.detect), ms(t.pose), ms(frame)]);
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
