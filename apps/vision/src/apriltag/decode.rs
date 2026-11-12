//! tag36h11 payload sampling and code lookup.

use super::geometry::{Homography, Vec2};
use super::image::ImageView;

/// Bit positions in tag cells, MSB first, as upstream AprilTag lays out tag36h11.
const BIT_X: [i8; 36] = [
    1, 2, 3, 4, 5, 2, 3, 4, 3, 6, 6, 6, 6, 6, 5, 5, 5, 4, 6, 5, 4, 3, 2, 5, 4, 3, 4, 1, 1, 1, 1, 1,
    2, 2, 2, 3,
];
const BIT_Y: [i8; 36] = [
    1, 1, 1, 1, 1, 2, 2, 2, 3, 1, 2, 3, 4, 5, 2, 3, 4, 3, 6, 6, 6, 6, 6, 5, 5, 5, 4, 6, 5, 4, 3, 2,
    5, 4, 3, 4,
];
const BITS: u32 = 36;
const MASK: u64 = (1 << BITS) - 1;
const BLOCK_BITS: u32 = 9;
const BLOCKS: usize = 4;

fn rotate90(code: u64) -> u64 {
    ((code << 9) | (code >> 27)) & MASK
}

struct Entry {
    code: u64,
    id: u16,
    /// Quarter turns that bring an observed code back to the canonical one.
    rotation: u8,
}

/// Every code in its four rotations, indexed by each 9-bit block. Any code within three bits
/// of an observation shares at least one block with it exactly.
pub struct Codebook {
    entries: Vec<Entry>,
    /// For each block, entry indices grouped by the block's value (CSR).
    starts: [Vec<u32>; BLOCKS],
    items: [Vec<u16>; BLOCKS],
}

pub struct Match {
    pub id: u16,
    pub hamming: u32,
    pub rotation: u8,
}

impl Codebook {
    pub fn tag36h11() -> Self {
        let codes = super::tag36h11::CODES;
        let mut entries = Vec::with_capacity(codes.len() * 4);
        for (id, &code) in codes.iter().enumerate() {
            let mut rotated = code;
            for k in 0..4u8 {
                entries.push(Entry { code: rotated, id: id as u16, rotation: (4 - k) % 4 });
                rotated = rotate90(rotated);
            }
        }
        let block = |code: u64, b: usize| ((code >> (b as u32 * BLOCK_BITS)) & 0x1ff) as usize;
        let starts = std::array::from_fn(|b| {
            let mut counts = vec![0u32; 513];
            for e in &entries {
                counts[block(e.code, b) + 1] += 1;
            }
            for i in 1..counts.len() {
                counts[i] += counts[i - 1];
            }
            counts
        });
        let items = std::array::from_fn(|b| {
            let starts: &Vec<u32> = &starts[b];
            let mut next = starts.clone();
            let mut items = vec![0u16; entries.len()];
            for (i, e) in entries.iter().enumerate() {
                let slot = &mut next[block(e.code, b)];
                items[*slot as usize] = i as u16;
                *slot += 1;
            }
            items
        });
        Self { entries, starts, items }
    }

    /// The closest code within `max_hamming` bits (at most 3).
    pub fn lookup(&self, observed: u64, max_hamming: u32) -> Option<Match> {
        let mut best: Option<Match> = None;
        for b in 0..BLOCKS {
            let value = ((observed >> (b as u32 * BLOCK_BITS)) & 0x1ff) as usize;
            let range = self.starts[b][value] as usize..self.starts[b][value + 1] as usize;
            for &i in &self.items[b][range] {
                let e = &self.entries[i as usize];
                let hamming = (e.code ^ observed).count_ones();
                if hamming <= max_hamming && best.as_ref().is_none_or(|m| hamming < m.hamming) {
                    best = Some(Match { id: e.id, hamming, rotation: e.rotation });
                }
            }
            if best.as_ref().is_some_and(|m| m.hamming == 0) {
                break;
            }
        }
        best
    }
}

/// Tag coordinate of a cell centre: cells -1..=8 across, the black square spans [-1, 1].
fn cell(c: i32) -> f32 {
    (c as f32 + 0.5) / 4.0 - 1.0
}

/// Cells of the ring `r` cells inside the black square's edge (-1 is the white margin, 0 the
/// black border).
fn ring(r: i32) -> impl Iterator<Item = (i32, i32)> {
    (r..=7 - r)
        .flat_map(move |y| (r..=7 - r).map(move |x| (x, y)))
        .filter(move |&(x, y)| x == r || y == r || x == 7 - r || y == 7 - r)
}

/// Least-squares weights that fit a plane `a*x + b*y + c` over tag coordinates to a ring's
/// cell values. The cells are fixed, so the fit is a fixed linear combination.
struct PlaneWeights<const N: usize>([[f32; N]; 3]);

impl<const N: usize> PlaneWeights<N> {
    fn new(r: i32) -> Self {
        let cells: Vec<[f64; 3]> =
            ring(r).map(|(x, y)| [cell(x) as f64, cell(y) as f64, 1.0]).collect();
        assert_eq!(cells.len(), N);
        let mut m = [[0f64; 3]; 3];
        for c in &cells {
            for i in 0..3 {
                for j in 0..3 {
                    m[i][j] += c[i] * c[j];
                }
            }
        }
        // The ring is symmetric about the centre, so the normal matrix is diagonal.
        let mut w = [[0f32; N]; 3];
        for (k, c) in cells.iter().enumerate() {
            for i in 0..3 {
                w[i][k] = (c[i] / m[i][i]) as f32;
            }
        }
        Self(w)
    }

    fn fit(&self, values: &[f32; N]) -> [f32; 3] {
        std::array::from_fn(|i| self.0[i].iter().zip(values).map(|(w, v)| w * v).sum())
    }
}

static MARGIN: std::sync::LazyLock<PlaneWeights<36>> =
    std::sync::LazyLock::new(|| PlaneWeights::new(-1));
static BORDER: std::sync::LazyLock<PlaneWeights<28>> =
    std::sync::LazyLock::new(|| PlaneWeights::new(0));

/// Why a read failed.
#[derive(Debug, PartialEq)]
pub enum Failure {
    /// Outside the image, or no dark border inside a light margin.
    Border,
    /// The border read dark, but the payload matched no code.
    Payload,
}

pub struct Decoded {
    pub id: u16,
    pub hamming: u32,
    pub rotation: u8,
    pub decision_margin: f32,
}

pub struct DecodeParams {
    pub max_hamming: u32,
    pub min_border_cells: u32,
    pub min_contrast: f32,
    pub sharpening: f32,
    /// Average several points per large cell, which suppresses noise but costs more.
    pub average: bool,
}

/// Reads the tag under homography `h` (tag coordinates to pixels).
pub fn decode(
    image: &ImageView,
    h: &Homography,
    codebook: &Codebook,
    params: &DecodeParams,
) -> Result<Decoded, Failure> {
    // Cell values over the 10x10 grid including the white margin, indexed [y + 1][x + 1].
    let mut values = [[0f32; 10]; 10];
    // Average a few points per cell when cells are large enough, which suppresses noise.
    let cell_px = h.scale_estimate() / 4.0;
    let spread = if params.average && cell_px >= 6.0 { 0.25 / 4.0 } else { 0.0 };
    let sample = |cx: i32, cy: i32| -> Option<f32> {
        let (x, y) = (cell(cx), cell(cy));
        let value = if spread > 0.0 {
            let mut sum = 0.0;
            for (dx, dy) in
                [(0.0, 0.0), (-spread, 0.0), (spread, 0.0), (0.0, -spread), (0.0, spread)]
            {
                sum += image.bilinear(h.project(Vec2::new(x + dx, y + dy)))?;
            }
            sum / 5.0
        } else {
            image.bilinear(h.project(Vec2::new(x, y)))?
        };
        Some(value)
    };
    let read = |values: &mut [[f32; 10]; 10], cx: i32, cy: i32| -> Option<f32> {
        let value = sample(cx, cy)?;
        values[(cy + 1) as usize][(cx + 1) as usize] = value;
        Some(value)
    };

    // The white margin and black border fit the light and dark levels across the tag.
    let mut margin = [0f32; 36];
    for (v, (cx, cy)) in margin.iter_mut().zip(ring(-1)) {
        *v = read(&mut values, cx, cy).ok_or(Failure::Border)?;
    }
    let mut border = [0f32; 28];
    for (v, (cx, cy)) in border.iter_mut().zip(ring(0)) {
        *v = read(&mut values, cx, cy).ok_or(Failure::Border)?;
    }
    let white = MARGIN.fit(&margin);
    let black = BORDER.fit(&border);
    let level = |p: [f32; 3], x: f32, y: f32| p[0] * x + p[1] * y + p[2];
    let threshold = |x: f32, y: f32| (level(white, x, y) + level(black, x, y)) / 2.0;
    if level(white, 0.0, 0.0) - level(black, 0.0, 0.0) < params.min_contrast {
        return Err(Failure::Border);
    }

    // Most of the border must read dark before the payload is worth reading.
    let dark =
        ring(0).zip(border).filter(|&((cx, cy), v)| v < threshold(cell(cx), cell(cy))).count();
    if (dark as u32) < params.min_border_cells {
        return Err(Failure::Border);
    }

    for i in 0..36 {
        read(&mut values, i32::from(BIT_X[i]), i32::from(BIT_Y[i])).ok_or(Failure::Border)?;
    }
    // Centre values on the local threshold over the black square.
    let mut centred = [[0f32; 8]; 8];
    for (y, row) in centred.iter_mut().enumerate() {
        for (x, v) in row.iter_mut().enumerate() {
            *v = values[y + 1][x + 1] - threshold(cell(x as i32), cell(y as i32));
        }
    }
    let mut code = 0u64;
    let (mut white_sum, mut white_n, mut black_sum, mut black_n) = (0f32, 1u32, 0f32, 1u32);
    for i in 0..36 {
        let (x, y) = (BIT_X[i] as usize, BIT_Y[i] as usize);
        let c = centred[y][x];
        let laplacian =
            4.0 * c - centred[y - 1][x] - centred[y + 1][x] - centred[y][x - 1] - centred[y][x + 1];
        let v = c + params.sharpening * laplacian;
        code <<= 1;
        if v > 0.0 {
            code |= 1;
            white_sum += v;
            white_n += 1;
        } else {
            black_sum -= v;
            black_n += 1;
        }
    }
    let found = codebook.lookup(code, params.max_hamming).ok_or(Failure::Payload)?;
    Ok(Decoded {
        id: found.id,
        hamming: found.hamming,
        rotation: found.rotation,
        decision_margin: (white_sum / white_n as f32).min(black_sum / black_n as f32),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lookup_finds_rotations_and_bit_errors() {
        let book = Codebook::tag36h11();
        let code = super::super::tag36h11::CODES[42];
        let observed = rotate90(code) ^ 0b101;
        let found = book.lookup(observed, 2).unwrap();
        assert_eq!((found.id, found.hamming, found.rotation), (42, 2, 3));
        assert!(book.lookup(observed, 1).is_none());
    }
}
