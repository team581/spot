//! `spot-vision corpus`: detection accuracy and speed on a labelled set of grayscale frames.
//!
//! The manifest is a JSON list of `{file, scenario, tags: [{id, corners, partial?}]}` with PGM
//! frames beside it. Corners are the black square's, with pixel centres at integer coordinates,
//! in either winding. A `partial: true` label can account for a detection but cannot earn recall.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::Context;
use nalgebra::Vector2;

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
    /// Print misses, unmatched detections, and matches more than 1 px off.
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
    #[serde(default)]
    partial: bool,
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
    unmatched: usize,
    ignored: usize,
    within_one_pixel: usize,
    times: Vec<f64>,
    corner_errors: Vec<f64>,
    offset: [f64; 2],
}

impl Stats {
    fn score(&mut self, frame: &Frame, detected: &[Detected], verbose: bool) {
        self.frames += 1;
        let mut used = vec![false; detected.len()];
        // Partial labels must not claim detections that could match a complete tag.
        for partial in [false, true] {
            for truth in frame.tags.iter().filter(|tag| tag.partial == partial) {
                self.tags += usize::from(!partial);
                let hit = detected
                    .iter()
                    .enumerate()
                    .filter(|(i, d)| !used[*i] && d.id == truth.id)
                    .map(|(i, d)| (quad_iou(&truth.corners, &d.corners), i, d))
                    .filter(|(iou, ..)| *iou >= 0.5)
                    .max_by(|a, b| a.0.total_cmp(&b.0));
                let Some((_, i, d)) = hit else {
                    if verbose && !partial {
                        println!("missed {} in {}", truth.id, frame.file);
                    }
                    continue;
                };
                used[i] = true;
                if partial {
                    self.ignored += 1;
                    continue;
                }
                self.found += 1;
                let (error, offset) = corner_error(&truth.corners, &d.corners);
                self.within_one_pixel += usize::from(error <= 1.0);
                self.corner_errors.push(error);
                self.offset[0] += offset[0];
                self.offset[1] += offset[1];
                if verbose && error > 1.0 {
                    println!("error {error:.1} px on {} in {}", truth.id, frame.file);
                }
            }
        }
        for (d, _) in detected.iter().zip(&used).filter(|(_, u)| !**u) {
            self.unmatched += 1;
            if verbose {
                println!("unmatched {} in {} at {:?}", d.id, frame.file, d.corners[0]);
            }
        }
    }
}

/// Area of intersection over area of union for two convex quads, in either winding.
fn quad_iou(a: &[[f64; 2]; 4], b: &[[f64; 2]; 4]) -> f64 {
    let twice_area = |p: &[Vector2<f64>]| {
        p.iter().zip(p.iter().cycle().skip(1)).map(|(u, v)| u.perp(v)).sum::<f64>()
    };
    let a = a.map(Vector2::from);
    let b = b.map(Vector2::from);
    let winding = twice_area(&b);
    if winding == 0.0 {
        return 0.0;
    }
    // Clip the first quad against the inside half-plane of each edge of the second.
    let mut polygon = a.to_vec();
    let mut clipped = Vec::with_capacity(8);
    for (p, q) in b.iter().zip(b.iter().cycle().skip(1)) {
        let signed_distance = |v| (q - p).perp(&(v - p)) * winding.signum();
        for (&u, &v) in polygon.iter().zip(polygon.iter().cycle().skip(1)) {
            let (du, dv) = (signed_distance(u), signed_distance(v));
            if (du < 0.0) != (dv < 0.0) {
                clipped.push(u + (v - u) * (du / (du - dv)));
            }
            if dv >= 0.0 {
                clipped.push(v);
            }
        }
        if clipped.is_empty() {
            return 0.0;
        }
        std::mem::swap(&mut polygon, &mut clipped);
        clipped.clear();
    }
    let intersection = twice_area(&polygon).abs();
    intersection / (twice_area(&a).abs() + winding.abs() - intersection)
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

/// The worst corner's distance and mean offset after least-squares corner alignment.
fn corner_error(truth: &[[f64; 2]; 4], found: &[[f64; 2]; 4]) -> (f64, [f64; 2]) {
    let (mut best, mut error, mut mean_offset) = (f64::INFINITY, f64::INFINITY, [0.0; 2]);
    for shift in 0..4 {
        for reverse in [false, true] {
            let (mut sum, mut worst) = (0.0, 0.0f64);
            let mut offset = [0.0; 2];
            for (i, t) in truth.iter().enumerate() {
                let j = if reverse { (shift + 4 - i) % 4 } else { (shift + i) % 4 };
                let (dx, dy) = (found[j][0] - t[0], found[j][1] - t[1]);
                let squared = dx * dx + dy * dy;
                sum += squared;
                worst = worst.max(squared);
                offset[0] += dx / 4.0;
                offset[1] += dy / 4.0;
            }
            if sum < best {
                (best, error, mean_offset) = (sum, worst.sqrt(), offset);
            }
        }
    }
    (error, mean_offset)
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
            stats.times.push(median(&mut times));
            stats.score(frame, &detected, self.verbose);
        }
        let width = groups.keys().map(String::len).max().unwrap_or(0).max(32);
        println!(
            "{:<width$} {:>6} {:>6} {:>6} {:>9} {:>7} {:>8} {:>9} {:>8} {:>8} {:>8} {:>8} {:>8} {:>13}",
            "group",
            "frames",
            "tags",
            "found",
            "unmatched",
            "ignored",
            "recall %",
            "prec. %",
            "≤1 px %",
            "p50 ms",
            "p95 ms",
            "err p50",
            "err max",
            "mean offset"
        );
        let mut all = Stats::default();
        for (name, mut s) in groups {
            print_row(&name, &mut s, width);
            all.frames += s.frames;
            all.tags += s.tags;
            all.found += s.found;
            all.unmatched += s.unmatched;
            all.ignored += s.ignored;
            all.within_one_pixel += s.within_one_pixel;
            all.times.extend(s.times);
            all.corner_errors.extend(s.corner_errors);
            all.offset[0] += s.offset[0];
            all.offset[1] += s.offset[1];
        }
        print_row("all", &mut all, width);
        Ok(())
    }
}

fn print_row(name: &str, s: &mut Stats, width: usize) {
    let n = s.found.max(1) as f64;
    let percent = |hits, total| 100.0 * hits as f64 / total as f64;
    println!(
        "{:<width$} {:>6} {:>6} {:>6} {:>9} {:>7} {:>8.2} {:>9.2} {:>8.2} {:>8.3} {:>8.3} {:>8.3} {:>8.3} {:>6.2},{:>6.2}",
        name,
        s.frames,
        s.tags,
        s.found,
        s.unmatched,
        s.ignored,
        percent(s.found, s.tags),
        percent(s.found, s.found + s.unmatched),
        percent(s.within_one_pixel, s.tags),
        median(&mut s.times),
        percentile(&mut s.times, 0.95),
        median(&mut s.corner_errors),
        percentile(&mut s.corner_errors, 1.0),
        s.offset[0] / n,
        s.offset[1] / n,
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uses_quad_overlap_not_bounding_boxes_and_accepts_half_overlap() {
        let diagonal = [[0.0, 0.0], [10.0, 8.0], [10.0, 10.0], [0.0, 2.0]];
        let other = diagonal.map(|[x, y]| [10.0 - x, y]);
        assert!(quad_iou(&diagonal, &other) < 0.5); // Same bounding box, opposite diagonals.

        let square = [[0.0, 0.0], [12.0, 0.0], [12.0, 12.0], [0.0, 12.0]];
        let mut shifted = square.map(|[x, y]| [x + 4.0, y]);
        shifted.reverse();
        assert_eq!(quad_iou(&square, &shifted), 0.5);
        assert!(quad_iou(&square, &shifted.map(|[x, y]| [x + 0.01, y])) < 0.5);
    }

    #[test]
    fn scores_visible_tags_before_partial_labels_and_counts_unmatched_detections() {
        let corners = |x| [[x, 0.0], [x + 12.0, 0.0], [x + 12.0, 12.0], [x, 12.0]];
        let truth = |id, x, partial| Truth { id, corners: corners(x), partial };
        let detection = |id, x| Detected { id, corners: corners(x) };
        let frame = Frame {
            file: "frame.pgm".into(),
            scenario: "test".into(),
            tags: vec![
                truth(9, 0.0, true),
                truth(9, 0.0, false),
                truth(9, 60.0, false),
                truth(10, 0.0, false),
                truth(12, 0.0, false),
                truth(42, 20.0, true),
            ],
        };
        let mut reversed = corners(1.0);
        reversed.rotate_left(1);
        reversed.reverse();
        let detections = [
            detection(9, 40.0),                    // Right ID at the wrong location.
            detection(11, 0.0),                    // Wrong ID at the right location.
            detection(9, 56.0),                    // Lower overlap than the next detection.
            detection(9, 57.0),                    // Better match, more than 1 px off.
            Detected { id: 9, corners: reversed }, // Exactly 1 px off.
            detection(12, 4.0),                    // Exactly 0.5 IoU.
            detection(42, 20.0),                   // Only a partial label here.
        ];
        let mut stats = Stats::default();
        stats.score(&frame, &detections, false);
        assert_eq!((stats.tags, stats.found, stats.unmatched, stats.ignored), (4, 3, 3, 1));
        assert_eq!(stats.within_one_pixel, 1);
        assert_eq!(stats.corner_errors, [1.0, 3.0, 4.0]);
    }
}
