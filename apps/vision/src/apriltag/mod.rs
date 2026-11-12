//! A tag36h11 detector that does full-resolution work only where tags are likely.
//!
//! 1. Dense stage (GPU on Jetson, CPU elsewhere; see `dense`): sample the image on a sparse
//!    grid fine enough to always land in a minimum-size tag's border, plus coarser grids (2x2
//!    averages) for larger tags, and threshold each against its local min/max, skipping tiles
//!    without enough contrast over the local noise.
//! 2. Join runs of dark samples into blobs and keep those with a tag's size, shape, and fill.
//! 3. Check that each candidate's outline is dark inside and light outside, fit its sides to
//!    the image edges, decode with a cheap border check first, then refine the edges and
//!    decode again.

mod blobs;
#[cfg(feature = "jetson")]
mod cuda;
mod decode;
mod dense;
mod edges;
mod geometry;
mod image;
mod tag36h11;

use decode::{Codebook, DecodeParams};
use edges::Search;
pub use geometry::Lens;
use geometry::{Homography, Vec2};
pub use image::ImageView;

#[derive(Debug, Clone)]
pub struct Config {
    /// The camera's lens, if calibrated, so tag edges are fit as straight lines.
    pub lens: Option<Lens>,
    /// Smallest black-square side, in pixels, that the sampling grid is guaranteed to hit.
    pub min_tag_px: u32,
    /// Smallest grey-level difference between a tag's black and its white margin.
    pub min_contrast: u8,
    /// Payload bits to correct (at most 3).
    pub max_hamming: u32,
    /// Border cells of 28 that must read dark before the payload is read.
    pub min_border_cells: u32,
    /// Cell sharpening before decoding, as upstream AprilTag's `decode_sharpening`.
    pub sharpening: f32,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            lens: None,
            min_tag_px: 32,
            min_contrast: 20,
            max_hamming: 1,
            min_border_cells: 22,
            sharpening: 0.25,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Tag {
    pub id: u32,
    pub hamming: u32,
    pub decision_margin: f32,
    /// Pixel corners with pixel centres at integer coordinates: bottom-left, bottom-right,
    /// top-right, top-left of the upright tag (upstream AprilTag's order).
    pub corners: [[f64; 2]; 4],
}

/// Where a frame's pixels are.
pub enum Source<'a> {
    Host(ImageView<'a>),
    /// Rows `pitch` bytes apart in CUDA device memory.
    #[cfg(feature = "jetson")]
    Device {
        ptr: *const u8,
        pitch: usize,
    },
}

pub struct Detector {
    config: Config,
    width: usize,
    height: usize,
    #[cfg(not(feature = "jetson"))]
    step: usize,
    levels: Vec<dense::Level>,
    #[cfg(not(feature = "jetson"))]
    dense: dense::Cpu,
    #[cfg(feature = "jetson")]
    dense: cuda::Gpu,
    codebook: Codebook,
    scratch: blobs::Scratch,
    candidates: Vec<blobs::Candidate>,
    points: Vec<(Vec2, f32)>,
}

struct Found {
    tag: Tag,
    quad: [Vec2; 4],
}

impl Detector {
    pub fn new(width: usize, height: usize, config: Config) -> anyhow::Result<Self> {
        anyhow::ensure!(width >= 64 && height >= 64, "image too small for the detector");
        anyhow::ensure!(config.max_hamming <= 3, "at most 3 bits can be corrected");
        // Samples ¾ of the smallest cell apart always hit the one-cell border's dark core.
        let step = ((0.75 * config.min_tag_px as f32 / 8.0) as usize).max(1);
        let levels = dense::layout(width, height, step);
        Ok(Self {
            #[cfg(not(feature = "jetson"))]
            dense: dense::Cpu::default(),
            #[cfg(feature = "jetson")]
            dense: cuda::Gpu::new(width, height, step, config.min_contrast, NOISE_FACTOR, &levels)?,
            config,
            width,
            height,
            #[cfg(not(feature = "jetson"))]
            step,
            levels,
            codebook: Codebook::tag36h11(),
            scratch: blobs::Scratch::default(),
            candidates: Vec::new(),
            points: Vec::new(),
        })
    }

    /// Detects tags in a frame of the detector's size.
    pub fn detect(&mut self, source: &Source) -> anyhow::Result<Vec<Tag>> {
        let host = match *source {
            Source::Host(view) => {
                anyhow::ensure!(
                    (view.width, view.height) == (self.width, self.height),
                    "image size mismatch"
                );
                #[cfg(feature = "jetson")]
                {
                    let device = self.dense.upload(view.data)?;
                    // SAFETY: `upload` returned a packed device copy of the image.
                    unsafe { self.dense.run(device, self.width)? };
                }
                #[cfg(not(feature = "jetson"))]
                self.dense.run(
                    &view,
                    &self.levels,
                    self.step,
                    self.config.min_contrast,
                    NOISE_FACTOR,
                );
                view
            }
            #[cfg(feature = "jetson")]
            Source::Device { ptr, pitch } => {
                // SAFETY: device frames have the detector's size, as the caller promises.
                unsafe { self.dense.run(ptr, pitch)? };
                ImageView::new(self.dense.image(), self.width, self.height, self.width)
                    .expect("the GPU copy covers the image")
            }
        };
        let mut found: Vec<Found> = Vec::new();
        // Coarse levels first: big tags are found once, and finer levels skip them.
        let mut candidates = std::mem::take(&mut self.candidates);
        for (k, level) in self.levels.iter().enumerate().rev() {
            candidates.clear();
            #[cfg(not(feature = "jetson"))]
            let mask = &self.dense.masks.levels[k];
            #[cfg(feature = "jetson")]
            let mask = self.dense.mask(k);
            blobs::candidates(level, mask, &mut self.scratch, &mut candidates);
            for candidate in &candidates {
                let centre = candidate.corners.iter().fold(Vec2::default(), |a, &p| a + p) * 0.25;
                if found.iter().any(|f| contains(&f.quad, centre)) {
                    continue;
                }
                if let Some(f) =
                    examine(&self.config, &self.codebook, &mut self.points, &host, candidate)
                {
                    found.push(f);
                }
            }
        }
        self.candidates = candidates;
        let mut tags: Vec<Tag> = found.into_iter().map(|f| f.tag).collect();
        tags.sort_by_key(|t| t.id);
        Ok(tags)
    }

    /// The last device frame's pixels, copied to host memory.
    #[cfg(feature = "jetson")]
    pub fn host_pixels(&self) -> &[u8] {
        self.dense.image()
    }
}

/// The dense stage's noise floor, in multiples of its roughness measure (about 1.1 sigma).
/// Higher values suppress more noise but miss more faint tags.
const NOISE_FACTOR: u32 = 4;

fn params(config: &Config, max_hamming: u32, average: bool) -> DecodeParams {
    DecodeParams {
        average,
        max_hamming,
        min_border_cells: config.min_border_cells,
        min_contrast: config.min_contrast as f32,
        sharpening: config.sharpening,
    }
}

/// Fits and decodes one candidate.
fn examine(
    config: &Config,
    codebook: &Codebook,
    points: &mut Vec<(Vec2, f32)>,
    image: &ImageView,
    candidate: &blobs::Candidate,
) -> Option<Found> {
    // Most candidates are texture or noise; a few samples across the outline reject them.
    if !edges::outline_contrast(
        image,
        &candidate.corners,
        candidate.step,
        config.min_contrast as f32,
    ) {
        return None;
    }
    let min_gradient = config.min_contrast as f32 / 8.0;
    let side = (0..4)
        .map(|i| (candidate.corners[(i + 1) % 4] - candidate.corners[i]).length())
        .sum::<f32>()
        / 4.0;
    // The rough outline joins dark sample centres, so it lies inside the edges, by up to a
    // couple of samples at corners that averaging rounded off.
    let coarse = Search {
        inward: candidate.step + 2.0,
        outward: if candidate.averaged { 2.5 } else { 1.0 } * candidate.step + 2.0,
        step: (candidate.step / 4.0).clamp(0.5, 2.0),
        spacing: (side / 12.0).clamp(1.5, 8.0),
        max_points: 8,
        min_gradient,
    };
    let quad = edges::fit_quad(image, &candidate.corners, &coarse, None, points)?;
    // Read loosely first: most non-tags fail here, before any refinement.
    let loose = params(config, config.max_hamming.clamp(2, 3), false);
    let h = Homography::from_corners(&quad)?;
    let quad = match decode::decode(image, &h, codebook, &loose) {
        Ok(_) => quad,
        Err(decode::Failure::Border) => return None,
        // A grey quiet zone on a bright background outlines the margin, not the square:
        // its "border" reads dark but the payload doesn't. Read the inner 8/10 before
        // refitting its edges.
        Err(decode::Failure::Payload) => {
            let d = decode::decode(image, &h.scaled(0.8), codebook, &loose).ok();
            let found = d.and_then(|_| {
                let inner = [(-0.8, -0.8), (0.8, -0.8), (0.8, 0.8), (-0.8, 0.8)]
                    .map(|(x, y)| h.project(Vec2::new(x, y)));
                let search = Search {
                    inward: side / 16.0 + 1.0,
                    outward: side / 16.0 + 1.0,
                    step: 0.5,
                    spacing: coarse.spacing,
                    max_points: 12,
                    min_gradient,
                };
                let quad = edges::fit_quad(image, &inner, &search, None, points)?;
                decode::decode(image, &Homography::from_corners(&quad)?, codebook, &loose).ok()?;
                Some(quad)
            });
            found?
        }
    };
    // Measurements every 1.5 px, up to a few dozen per side, refit until the corners settle.
    let fine =
        Search { inward: 2.5, outward: 2.5, step: 0.5, spacing: 1.5, max_points: 32, min_gradient };
    let mut refined = quad;
    for _ in 0..3 {
        let Some(next) = edges::fit_quad(image, &refined, &fine, config.lens.as_ref(), points)
        else {
            break;
        };
        let moved = (0..4).map(|i| (next[i] - refined[i]).length()).fold(0f32, f32::max);
        refined = next;
        if moved < 0.1 {
            break;
        }
    }
    let h = Homography::from_corners(&refined)?;
    let decoded =
        decode::decode(image, &h, codebook, &params(config, config.max_hamming, true)).ok()?;
    let h = h.rotated(decoded.rotation);
    let corners = [(-1.0, 1.0), (1.0, 1.0), (1.0, -1.0), (-1.0, -1.0)].map(|(x, y)| {
        let p = h.project(Vec2::new(x, y));
        [p.x as f64, p.y as f64]
    });
    Some(Found {
        tag: Tag {
            id: decoded.id.into(),
            hamming: decoded.hamming,
            decision_margin: decoded.decision_margin,
            corners,
        },
        quad: refined,
    })
}

/// Whether `p` is inside the clockwise convex quad.
fn contains(quad: &[Vec2; 4], p: Vec2) -> bool {
    (0..4).all(|i| (quad[(i + 1) % 4] - quad[i]).cross(p - quad[i]) >= 0.0)
}
