//! Fits a quadrilateral's sides to the image edges at full resolution.

use super::geometry::{Lens, Line, Vec2};
use super::image::ImageView;

pub struct Search {
    /// How far inside and outside the current side to look for the edge, in pixels.
    pub inward: f32,
    pub outward: f32,
    /// Spacing of samples across the edge.
    pub step: f32,
    /// Spacing of measurements along the side.
    pub spacing: f32,
    /// Most measurements per side.
    pub max_points: usize,
    /// Smallest gradient peak, in grey levels per pixel, that counts as an edge.
    pub min_gradient: f32,
}

const MAX_PROFILE: usize = 96;

/// Locates the dark-to-light edge across the side from `a` to `b` of a clockwise quad, whose
/// dark interior is on the right.
fn fit_side(
    image: &ImageView,
    a: Vec2,
    b: Vec2,
    search: &Search,
    lens: Option<&Lens>,
    points: &mut Vec<(Vec2, f32)>,
) -> Option<Line> {
    let side = b - a;
    let length = side.length();
    if length < 4.0 {
        return None;
    }
    let along = side * (1.0 / length);
    let outward = Vec2::new(along.y, -along.x);
    let inner = ((search.inward / search.step).ceil() as usize).min(MAX_PROFILE / 2 - 2);
    let outer = ((search.outward / search.step).ceil() as usize).min(MAX_PROFILE / 2 - 2);
    let count = ((0.8 * length / search.spacing) as usize).clamp(4, search.max_points);
    let min_peak = search.min_gradient * 2.0 * search.step;
    points.clear();
    let mut values = [0f32; MAX_PROFILE];
    let mut gradient = [0f32; MAX_PROFILE];
    'point: for i in 0..count {
        // Stay clear of the corners, where the other sides' edges interfere.
        let t = 0.1 + 0.8 * (i as f32 + 0.5) / count as f32;
        let base = a + side * t;
        let n = inner + outer + 3;
        for (k, v) in values[..n].iter_mut().enumerate() {
            let u = (k as f32 - (inner + 1) as f32) * search.step;
            match image.bilinear(base + outward * u) {
                Some(value) => *v = value,
                None => continue 'point,
            }
        }
        let mut strongest = f32::MIN;
        for k in 1..n - 1 {
            gradient[k] = values[k + 1] - values[k - 1];
            strongest = strongest.max(gradient[k]);
        }
        if strongest < min_peak {
            continue;
        }
        // Edges between payload cells inside the tag can be as strong as its outline, which is
        // the outermost strong dark-to-light edge.
        let Some(peak) = (1..n - 1).rev().find(|&k| {
            gradient[k] >= 0.6 * strongest
                && (k + 1 == n - 1 || gradient[k] >= gradient[k + 1])
                && gradient[k] >= gradient[k - 1]
        }) else {
            continue;
        };
        let top = gradient[peak];
        // The centre of the gradient around the peak locates a blurred edge exactly.
        let floor = 0.25 * top;
        let (mut lo, mut hi) = (peak, peak);
        while lo > 1 && gradient[lo - 1] > floor {
            lo -= 1;
        }
        while hi < n - 2 && gradient[hi + 1] > floor {
            hi += 1;
        }
        let (mut sum, mut moment) = (0.0, 0.0);
        for (k, &g) in gradient.iter().enumerate().take(hi + 1).skip(lo) {
            let g = g - floor;
            sum += g;
            moment += g * k as f32;
        }
        let u = (moment / sum - (inner + 1) as f32) * search.step;
        points.push((base + outward * u, top));
    }
    if points.len() < 3 {
        return None;
    }
    // Under lens distortion the edge is straight only in undistorted space.
    if let Some(lens) = lens {
        for (p, _) in points.iter_mut() {
            *p = lens.undistort(*p)?;
        }
    }
    // Start from the line through two measurements that most others agree with, so stray
    // measurements can't drag the fit, then refit to those that agree.
    let agree = (0.25 * (search.inward + search.outward)).clamp(0.75, 2.0);
    let half = points.len() / 2;
    let (mut best, mut best_count) = (None, 0);
    for i in 0..half.max(1) {
        let (p, q) = (points[i].0, points[(i + half).min(points.len() - 1)].0);
        let along = q - p;
        if along.length() < 1.0 {
            continue;
        }
        let line = Line { point: p, direction: along * (1.0 / along.length()) };
        let count = points.iter().filter(|&&(r, _)| line.distance(r).abs() <= agree).count();
        if count > best_count {
            (best, best_count) = (Some(line), count);
        }
    }
    let seed = best?;
    points.retain(|&(p, _)| seed.distance(p).abs() <= agree);
    if points.len() < 3 {
        return None;
    }
    let line = Line::fit(points)?;
    // Drop measurements that disagree with the rest of the edge, such as an obstruction.
    let mut residuals = [0f32; 512];
    let n = points.len().min(residuals.len());
    for (r, &(p, _)) in residuals.iter_mut().zip(points.iter()) {
        *r = line.distance(p).abs();
    }
    let median = *residuals[..n].select_nth_unstable_by(n / 2, f32::total_cmp).1;
    let tolerance = (3.0 * median).max(0.5 * search.step).max(0.3);
    let before = points.len();
    points.retain(|&(p, _)| line.distance(p).abs() <= tolerance);
    if points.len() < 3 || points.len() * 2 < before {
        return None;
    }
    if points.len() == before { Some(line) } else { Line::fit(points) }
}

/// Refits all four sides and intersects them, or `None` if any side has no clear edge. With a
/// lens, the sides are fit in undistorted space.
pub fn fit_quad(
    image: &ImageView,
    quad: &[Vec2; 4],
    search: &Search,
    lens: Option<&Lens>,
    scratch: &mut Vec<(Vec2, f32)>,
) -> Option<[Vec2; 4]> {
    let mut lines = [Line { point: Vec2::default(), direction: Vec2::default() }; 4];
    for i in 0..4 {
        lines[i] = fit_side(image, quad[i], quad[(i + 1) % 4], search, lens, scratch)?;
    }
    let mut corners = [Vec2::default(); 4];
    for i in 0..4 {
        corners[i] = lines[(i + 3) % 4].intersect(&lines[i])?;
        if let Some(lens) = lens {
            corners[i] = lens.distort(corners[i]);
        }
        // A corner that moved far beyond the search range came from a bad line.
        if (corners[i] - quad[i]).length() > 3.0 * search.inward.max(search.outward) + 2.0 {
            return None;
        }
    }
    let area = 0.5 * (0..4).map(|i| corners[i].cross(corners[(i + 1) % 4])).sum::<f32>();
    let convex = (0..4).all(|i| {
        let e0 = corners[(i + 1) % 4] - corners[i];
        let e1 = corners[(i + 2) % 4] - corners[(i + 1) % 4];
        e0.cross(e1) > 0.0
    });
    (area > 16.0 && convex).then_some(corners)
}

/// Whether a rough outline has a dark inside and a light outside along most of its sides: a
/// cheap test that rejects noise and texture before fitting edges.
pub fn outline_contrast(image: &ImageView, quad: &[Vec2; 4], step: f32, min_contrast: f32) -> bool {
    let side = (0..4).map(|i| (quad[(i + 1) % 4] - quad[i]).length()).sum::<f32>() / 4.0;
    let cell = side / 8.0;
    // The rough outline lies up to about a sample inside the true one.
    let (inside, outside) = (0.3 * cell, 0.5 * (cell + step));
    let mut agree = 0;
    for i in 0..4 {
        let (a, b) = (quad[i], quad[(i + 1) % 4]);
        let along = (b - a) * (1.0 / (b - a).length());
        let normal = Vec2::new(along.y, -along.x);
        for t in [0.3, 0.5, 0.7] {
            let p = a + (b - a) * t;
            let (Some(dark), Some(light)) =
                (image.bilinear(p - normal * inside), image.bilinear(p + normal * outside))
            else {
                continue;
            };
            agree += u32::from(light - dark >= 0.5 * min_contrast);
        }
    }
    agree >= 8
}
