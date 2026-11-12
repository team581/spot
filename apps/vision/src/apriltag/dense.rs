//! The dense stage: a sparse sample pyramid, thresholded against local contrast and noise
//! into one bit per sample. Jetson builds run it on the GPU (`cpp/shim/dense.cu`), which must
//! produce exactly the same bits as the CPU version here; there the CPU version is only the
//! tests' reference.

use super::geometry::Vec2;
use super::image::ImageView;

/// Samples per tile side for local min/max.
#[cfg_attr(feature = "jetson", allow(dead_code))]
pub const TILE: usize = 4;
/// Tiles per noise region side.
#[cfg_attr(feature = "jetson", allow(dead_code))]
const REGION: usize = 8;
/// Coarser levels add little at camera resolutions, and the GPU kernel computes up to four.
pub const MAX_LEVELS: usize = 4;

/// One level of the sample pyramid.
#[derive(Debug, Clone, PartialEq)]
pub struct Level {
    /// Pixels between samples.
    pub step: f32,
    /// Pixel coordinate of sample 0.
    pub offset: f32,
    pub width: usize,
    pub height: usize,
    /// Whether samples average several pixels (every level but the first).
    pub averaged: bool,
    /// Blob extents, in samples, that this level looks for.
    pub min_extent: usize,
    pub max_extent: usize,
}

impl Level {
    pub fn pixel(&self, x: f32, y: f32) -> Vec2 {
        Vec2::new(self.offset + x * self.step, self.offset + y * self.step)
    }

    /// 32-bit words per mask row.
    pub fn words(&self) -> usize {
        self.width.div_ceil(32)
    }
}

/// The pyramid for an image size: the finest level samples every `step` pixels from
/// `step / 2`, and each coarser level averages 2x2 samples of the one before.
pub fn layout(width: usize, height: usize, step: usize) -> Vec<Level> {
    let start = step / 2;
    let (mut w, mut h) = ((width - start).div_ceil(step), (height - start).div_ceil(step));
    let (mut s, mut offset) = (step as f32, start as f32);
    let mut levels = Vec::new();
    loop {
        let first = levels.is_empty();
        levels.push(Level {
            step: s,
            offset,
            width: w,
            height: h,
            averaged: !first,
            min_extent: if first { 5 } else { 10 },
            max_extent: 48,
        });
        if w / 2 < 24 || h / 2 < 24 || levels.len() == MAX_LEVELS {
            break;
        }
        offset += s / 2.0;
        s *= 2.0;
        w /= 2;
        h /= 2;
    }
    levels.last_mut().unwrap().max_extent = usize::MAX;
    levels
}

/// Dark-sample bits for every level, rows of `Level::words` words, bit `x % 32` of word
/// `x / 32` for sample `x`.
#[derive(Default)]
#[cfg_attr(feature = "jetson", allow(dead_code))]
pub struct Masks {
    pub levels: Vec<Vec<u32>>,
}

/// The CPU dense stage.
#[derive(Default)]
#[cfg_attr(feature = "jetson", allow(dead_code))]
pub struct Cpu {
    data: Vec<Vec<u8>>,
    tile_min: Vec<u8>,
    tile_max: Vec<u8>,
    tile_rough: Vec<u8>,
    floor: Vec<u8>,
    thresholds: Vec<u8>,
    pub masks: Masks,
}

#[cfg_attr(feature = "jetson", allow(dead_code))]
impl Cpu {
    pub fn run(
        &mut self,
        image: &ImageView,
        levels: &[Level],
        step: usize,
        min_contrast: u8,
        noise_factor: u32,
    ) {
        let start = step / 2;
        self.data.resize_with(levels.len(), Vec::new);
        self.masks.levels.resize_with(levels.len(), Vec::new);
        for (k, level) in levels.iter().enumerate() {
            let (w, h) = (level.width, level.height);
            let mut data = std::mem::take(&mut self.data[k]);
            data.resize(w * h, 0);
            if k == 0 {
                for y in 0..h {
                    let row = image.row(start + y * step);
                    for (x, v) in data[y * w..(y + 1) * w].iter_mut().enumerate() {
                        *v = row[start + x * step];
                    }
                }
            } else {
                let fine = &self.data[k - 1];
                let fw = levels[k - 1].width;
                for y in 0..h {
                    for x in 0..w {
                        let at = |dx, dy| fine[(2 * y + dy) * fw + 2 * x + dx] as u16;
                        data[y * w + x] =
                            ((at(0, 0) + at(1, 0) + at(0, 1) + at(1, 1) + 2) >> 2) as u8;
                    }
                }
            }
            self.threshold(&data, level, min_contrast, noise_factor, k);
            self.data[k] = data;
        }
    }

    fn threshold(
        &mut self,
        data: &[u8],
        level: &Level,
        min_contrast: u8,
        noise_factor: u32,
        k: usize,
    ) {
        let (w, h) = (level.width, level.height);
        let (tw, th) = (w.div_ceil(TILE), h.div_ceil(TILE));
        for buffer in [&mut self.tile_min, &mut self.tile_max, &mut self.tile_rough] {
            buffer.clear();
            buffer.resize(tw * th, 0);
        }
        for ty in 0..th {
            for tx in 0..tw {
                let (mut lo, mut hi, mut rough) = (255u8, 0u8, 0u32);
                for y in ty * TILE..((ty + 1) * TILE).min(h) {
                    let chunk = &data[y * w + tx * TILE..y * w + ((tx + 1) * TILE).min(w)];
                    for &v in chunk {
                        lo = lo.min(v);
                        hi = hi.max(v);
                    }
                    rough += chunk.windows(2).map(|p| p[0].abs_diff(p[1]) as u32).sum::<u32>();
                }
                let i = ty * tw + tx;
                self.tile_min[i] = lo;
                self.tile_max[i] = hi;
                self.tile_rough[i] = (rough / (TILE * (TILE - 1)) as u32).min(255) as u8;
            }
        }
        // Required contrast from local noise. A low percentile of tile roughness ignores tiles
        // with edges, so tags don't raise their own floor. Mean absolute neighbour difference
        // is about 1.1 sigma, so the floor is `noise_factor` times about 1.1 sigma.
        self.floor.clear();
        self.floor.resize(tw * th, 0);
        let mut values = Vec::with_capacity(REGION * REGION);
        for ry in (0..th).step_by(REGION) {
            for rx in (0..tw).step_by(REGION) {
                values.clear();
                for y in ry..(ry + REGION).min(th) {
                    values.extend_from_slice(
                        &self.tile_rough[y * tw + rx..y * tw + (rx + REGION).min(tw)],
                    );
                }
                let quarter = values.len() / 4;
                let quartile = *values.select_nth_unstable(quarter).1;
                let floor = ((quartile as u32 * noise_factor).min(255) as u8).max(min_contrast);
                for y in ry..(ry + REGION).min(th) {
                    self.floor[y * tw + rx..y * tw + (rx + REGION).min(tw)].fill(floor);
                }
            }
        }
        // Each tile's threshold is the midpoint of its 3x3 neighbourhood, if that has enough
        // contrast; otherwise nothing in it is dark.
        self.thresholds.clear();
        self.thresholds.resize(tw * th, 0);
        for ty in 0..th {
            for tx in 0..tw {
                let (mut lo, mut hi) = (255u8, 0u8);
                for y in ty.saturating_sub(1)..(ty + 2).min(th) {
                    for x in tx.saturating_sub(1)..(tx + 2).min(tw) {
                        lo = lo.min(self.tile_min[y * tw + x]);
                        hi = hi.max(self.tile_max[y * tw + x]);
                    }
                }
                let i = ty * tw + tx;
                if hi - lo >= self.floor[i] {
                    self.thresholds[i] = (lo as u16 + hi as u16).div_ceil(2) as u8;
                }
            }
        }
        let words = level.words();
        let mask = &mut self.masks.levels[k];
        mask.clear();
        mask.resize(words * h, 0);
        for y in 0..h {
            let thresholds = &self.thresholds[(y / TILE) * tw..(y / TILE + 1) * tw];
            for (x, &v) in data[y * w..(y + 1) * w].iter().enumerate() {
                if v < thresholds[x / TILE] {
                    mask[y * words + x / 32] |= 1 << (x % 32);
                }
            }
        }
    }
}
