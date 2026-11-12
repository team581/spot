//! `spot-vision corpus`: detection accuracy and speed on a labelled set of grayscale frames.
//!
//! The manifest is a JSON list of `{file, scenario, tags: [{id, corners}]}` with PGM frames
//! beside it. Corners are the black square's, with pixel centres at integer coordinates, in
//! any rotation of upstream AprilTag's winding.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::Context;

use crate::apriltag;

#[derive(clap::Args)]
pub struct Corpus {
    manifest: PathBuf,
    /// Timed calls per frame after one warm-up call.
    #[arg(long, default_value_t = 5)]
    repetitions: usize,
    /// Only frames whose file name contains this text.
    #[arg(long)]
    filter: Option<String>,
    /// Print each missed or invented tag.
    #[arg(long)]
    verbose: bool,
}

#[derive(serde::Deserialize)]
struct Frame {
    file: String,
    scenario: String,
    tags: Vec<Truth>,
}

#[derive(serde::Deserialize)]
struct Truth {
    id: u32,
    corners: [[f64; 2]; 4],
}

fn read_pgm(path: &Path) -> anyhow::Result<(Vec<u8>, u32, u32)> {
    let data = std::fs::read(path).with_context(|| path.display().to_string())?;
    let mut fields = Vec::new();
    let mut i = 0;
    while fields.len() < 4 {
        while data[i].is_ascii_whitespace() {
            i += 1;
        }
        let start = i;
        while !data[i].is_ascii_whitespace() {
            i += 1;
        }
        fields.push(std::str::from_utf8(&data[start..i])?.to_owned());
    }
    anyhow::ensure!(
        fields[0] == "P5" && fields[3] == "255",
        "{}: not an 8-bit PGM",
        path.display()
    );
    let (width, height): (u32, u32) = (fields[1].parse()?, fields[2].parse()?);
    let pixels = data[i + 1..].to_vec();
    anyhow::ensure!(pixels.len() == (width * height) as usize, "{}: truncated", path.display());
    Ok((pixels, width, height))
}

struct Detected {
    id: u32,
    corners: [[f64; 2]; 4],
}

/// The detector for the current image size. On Jetson, each frame is first copied to device
/// memory, outside the timed calls, as frames arrive from NVJPG.
#[derive(Default)]
struct Runner {
    detector: Option<(apriltag::Detector, (usize, usize))>,
    #[cfg(feature = "jetson")]
    device: Option<(usize, *const u8)>,
}

impl Runner {
    /// `frame` changes whenever the image does.
    fn detect(&mut self, pixels: &[u8], size: (usize, usize), frame: usize) -> Vec<Detected> {
        if self.detector.as_ref().is_none_or(|(_, s)| *s != size) {
            let detector = apriltag::Detector::new(size.0, size.1, apriltag::Config::default());
            self.detector = Some((detector.expect("detector"), size));
            #[cfg(feature = "jetson")]
            {
                self.device = None;
            }
        }
        let detector = &mut self.detector.as_mut().unwrap().0;
        #[cfg(feature = "jetson")]
        let source = {
            if self.device.is_none_or(|(uploaded, _)| uploaded != frame) {
                let apriltag::Source::Device { ptr, .. } = detector.upload(pixels).expect("upload")
                else {
                    unreachable!()
                };
                self.device = Some((frame, ptr));
            }
            apriltag::Source::Device { ptr: self.device.unwrap().1, pitch: size.0 }
        };
        #[cfg(not(feature = "jetson"))]
        let source = {
            let _ = frame;
            let view = apriltag::ImageView::new(pixels, size.0, size.1, size.0);
            apriltag::Source::Host(view.expect("image size"))
        };
        let tags = detector.detect(&source).expect("detect");
        tags.into_iter().map(|t| Detected { id: t.id, corners: t.corners }).collect()
    }
}

#[derive(Default)]
struct Stats {
    frames: usize,
    tags: usize,
    found: usize,
    false_ids: usize,
    times: Vec<f64>,
    corner_errors: Vec<f64>,
    offset: [f64; 2],
}

fn median(values: &mut [f64]) -> f64 {
    if values.is_empty() {
        return f64::NAN;
    }
    values.sort_by(f64::total_cmp);
    values[values.len() / 2]
}

fn percentile(values: &mut [f64], p: f64) -> f64 {
    if values.is_empty() {
        return f64::NAN;
    }
    values.sort_by(f64::total_cmp);
    values[((values.len() - 1) as f64 * p).round() as usize]
}

/// The worst corner's distance after the best cyclic alignment, and the mean offset there.
fn corner_error(truth: &[[f64; 2]; 4], found: &[[f64; 2]; 4]) -> (f64, [f64; 2]) {
    let mut best = (f64::MAX, [0.0; 2]);
    for shift in 0..4 {
        for reverse in [false, true] {
            let mut worst = 0f64;
            let mut offset = [0.0; 2];
            for (i, t) in truth.iter().enumerate() {
                let j = if reverse { (shift + 4 - i) % 4 } else { (shift + i) % 4 };
                let (dx, dy) = (found[j][0] - t[0], found[j][1] - t[1]);
                worst = worst.max(dx.hypot(dy));
                offset[0] += dx / 4.0;
                offset[1] += dy / 4.0;
            }
            if worst < best.0 {
                best = (worst, offset);
            }
        }
    }
    best
}

impl Corpus {
    pub fn run(self) -> anyhow::Result<()> {
        let frames: Vec<Frame> = serde_json::from_slice(&std::fs::read(&self.manifest)?)?;
        let dir = self.manifest.parent().unwrap_or(Path::new("."));
        let mut runner = Runner::default();
        let mut groups: BTreeMap<String, Stats> = BTreeMap::new();
        for (index, frame) in frames.iter().enumerate() {
            if self.filter.as_ref().is_some_and(|f| !frame.file.contains(f.as_str())) {
                continue;
            }
            let (pixels, width, height) = read_pgm(&dir.join(&frame.file))?;
            let size = (width as usize, height as usize);
            let mut detected = runner.detect(&pixels, size, index);
            let mut times = Vec::with_capacity(self.repetitions);
            for _ in 0..self.repetitions {
                let start = Instant::now();
                detected = runner.detect(&pixels, size, index);
                times.push(start.elapsed().as_secs_f64() * 1e3);
            }
            let key = if frame.scenario == "range" {
                frame.file[..9].to_owned()
            } else {
                format!("{width}x{height} {}", frame.scenario)
            };
            let stats = groups.entry(key).or_default();
            stats.frames += 1;
            stats.tags += frame.tags.len();
            stats.times.push(median(&mut times));
            let mut used = vec![false; detected.len()];
            for truth in &frame.tags {
                let hit = detected.iter().enumerate().find(|(i, d)| !used[*i] && d.id == truth.id);
                match hit {
                    Some((i, d)) => {
                        used[i] = true;
                        stats.found += 1;
                        let (error, offset) = corner_error(&truth.corners, &d.corners);
                        if self.verbose && error > 1.0 {
                            println!(
                                "error {error:.1} px on {} in {}: {:?}",
                                truth.id,
                                frame.file,
                                d.corners.map(|c| c.map(|v| v.round()))
                            );
                        }
                        stats.corner_errors.push(error);
                        stats.offset[0] += offset[0];
                        stats.offset[1] += offset[1];
                    }
                    None if self.verbose => println!("missed {} in {}", truth.id, frame.file),
                    None => {}
                }
            }
            for (d, _) in detected.iter().zip(&used).filter(|(_, u)| !**u) {
                stats.false_ids += 1;
                if self.verbose {
                    println!("invented {} in {} at {:?}", d.id, frame.file, d.corners[0]);
                }
            }
        }
        println!(
            "{:<32} {:>6} {:>5} {:>5} {:>5} {:>8} {:>8} {:>8} {:>8} {:>13}",
            "group",
            "frames",
            "tags",
            "found",
            "false",
            "p50 ms",
            "p95 ms",
            "err p50",
            "err max",
            "mean offset"
        );
        let mut all = Stats::default();
        for (name, mut s) in groups {
            print_row(&name, &mut s);
            all.frames += s.frames;
            all.tags += s.tags;
            all.found += s.found;
            all.false_ids += s.false_ids;
            all.times.extend(s.times);
            all.corner_errors.extend(s.corner_errors);
            all.offset[0] += s.offset[0];
            all.offset[1] += s.offset[1];
        }
        print_row("all", &mut all);
        Ok(())
    }
}

fn print_row(name: &str, s: &mut Stats) {
    let n = s.found.max(1) as f64;
    println!(
        "{:<32} {:>6} {:>5} {:>5} {:>5} {:>8.3} {:>8.3} {:>8.3} {:>8.3} {:>6.2},{:>6.2}",
        name,
        s.frames,
        s.tags,
        s.found,
        s.false_ids,
        median(&mut s.times),
        percentile(&mut s.times, 0.95),
        median(&mut s.corner_errors),
        percentile(&mut s.corner_errors, 1.0),
        s.offset[0] / n,
        s.offset[1] / n,
    );
}
