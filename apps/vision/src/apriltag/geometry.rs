//! Points, lines, and homographies.

use std::ops::{Add, Mul, Sub};

#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Vec2 {
    pub x: f32,
    pub y: f32,
}

impl Vec2 {
    pub const fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }

    pub fn dot(self, o: Self) -> f32 {
        self.x * o.x + self.y * o.y
    }

    pub fn cross(self, o: Self) -> f32 {
        self.x * o.y - self.y * o.x
    }

    pub fn length(self) -> f32 {
        self.dot(self).sqrt()
    }
}

impl Add for Vec2 {
    type Output = Self;
    fn add(self, o: Self) -> Self {
        Self::new(self.x + o.x, self.y + o.y)
    }
}

impl Sub for Vec2 {
    type Output = Self;
    fn sub(self, o: Self) -> Self {
        Self::new(self.x - o.x, self.y - o.y)
    }
}

impl Mul<f32> for Vec2 {
    type Output = Self;
    fn mul(self, s: f32) -> Self {
        Self::new(self.x * s, self.y * s)
    }
}

/// Pinhole intrinsics with OpenCV's five-coefficient distortion model, for fitting tag edges
/// as straight lines in undistorted space.
#[derive(Debug, Clone, Copy)]
pub struct Lens {
    pub fx: f32,
    pub fy: f32,
    pub cx: f32,
    pub cy: f32,
    /// `[k1, k2, p1, p2, k3]`
    pub distortion: [f32; 5],
}

impl Lens {
    /// Normalized coordinates to distorted ones.
    fn distort_normalized(&self, x: f32, y: f32) -> (f32, f32) {
        let [k1, k2, p1, p2, k3] = self.distortion;
        let r2 = x * x + y * y;
        let radial = 1.0 + r2 * (k1 + r2 * (k2 + r2 * k3));
        (
            x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x),
            y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y,
        )
    }

    /// A pixel as it would appear without distortion.
    pub fn undistort(&self, p: Vec2) -> Vec2 {
        let (x0, y0) = ((p.x - self.cx) / self.fx, (p.y - self.cy) / self.fy);
        let (mut x, mut y) = (x0, y0);
        // Fixed-point iteration, as OpenCV's undistortPoints; a few steps suffice for the
        // sub-pixel shifts along one edge.
        for _ in 0..5 {
            let (dx, dy) = self.distort_normalized(x, y);
            x += x0 - dx;
            y += y0 - dy;
        }
        Vec2::new(self.fx * x + self.cx, self.fy * y + self.cy)
    }

    /// An undistorted pixel where the camera sees it.
    pub fn distort(&self, p: Vec2) -> Vec2 {
        let (x, y) = self.distort_normalized((p.x - self.cx) / self.fx, (p.y - self.cy) / self.fy);
        Vec2::new(self.fx * x + self.cx, self.fy * y + self.cy)
    }
}

/// A line through `point` along unit `direction`.
#[derive(Debug, Clone, Copy)]
pub struct Line {
    pub point: Vec2,
    pub direction: Vec2,
}

impl Line {
    pub fn intersect(&self, o: &Line) -> Option<Vec2> {
        let denom = self.direction.cross(o.direction);
        if denom.abs() < 1e-6 {
            return None;
        }
        let t = (o.point - self.point).cross(o.direction) / denom;
        Some(self.point + self.direction * t)
    }

    /// Weighted total least squares through `points` (point, weight).
    pub fn fit(points: &[(Vec2, f32)]) -> Option<Line> {
        let total: f32 = points.iter().map(|p| p.1).sum();
        if points.len() < 2 || total <= 0.0 {
            return None;
        }
        let mean = points.iter().fold(Vec2::default(), |a, &(p, w)| a + p * w) * (1.0 / total);
        let (mut xx, mut xy, mut yy) = (0.0, 0.0, 0.0);
        for &(p, w) in points {
            let d = p - mean;
            xx += w * d.x * d.x;
            xy += w * d.x * d.y;
            yy += w * d.y * d.y;
        }
        // Principal axis of the scatter.
        let angle = 0.5 * (2.0 * xy).atan2(xx - yy);
        Some(Line { point: mean, direction: Vec2::new(angle.cos(), angle.sin()) })
    }

    pub fn distance(&self, p: Vec2) -> f32 {
        self.direction.cross(p - self.point)
    }
}

/// Maps tag coordinates, [-1, 1] across the black square, to pixels.
#[derive(Debug, Clone, Copy)]
pub struct Homography(pub [[f64; 3]; 3]);

impl Homography {
    /// From pixel corners at tag coordinates (-1,-1), (1,-1), (1,1), (-1,1).
    pub fn from_corners(corners: &[Vec2; 4]) -> Option<Self> {
        const TAG: [(f64, f64); 4] = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)];
        // Solve A h = b for the eight unknowns, h33 = 1.
        let mut a = [[0f64; 9]; 8];
        for (i, (&(x, y), c)) in TAG.iter().zip(corners).enumerate() {
            let (u, v) = (c.x as f64, c.y as f64);
            a[2 * i] = [x, y, 1.0, 0.0, 0.0, 0.0, -x * u, -y * u, u];
            a[2 * i + 1] = [0.0, 0.0, 0.0, x, y, 1.0, -x * v, -y * v, v];
        }
        for col in 0..8 {
            let pivot = (col..8).max_by(|&i, &j| a[i][col].abs().total_cmp(&a[j][col].abs()))?;
            if a[pivot][col].abs() < 1e-12 {
                return None;
            }
            a.swap(col, pivot);
            for row in 0..8 {
                if row != col {
                    let f = a[row][col] / a[col][col];
                    let pivot_row = a[col];
                    for (v, p) in a[row].iter_mut().zip(pivot_row).skip(col) {
                        *v -= f * p;
                    }
                }
            }
        }
        let h = |i: usize| a[i][8] / a[i][i];
        Some(Self([[h(0), h(1), h(2)], [h(3), h(4), h(5)], [h(6), h(7), 1.0]]))
    }

    pub fn project(&self, p: Vec2) -> Vec2 {
        let m = &self.0;
        let (x, y) = (p.x as f64, p.y as f64);
        let w = m[2][0] * x + m[2][1] * y + m[2][2];
        Vec2::new(
            ((m[0][0] * x + m[0][1] * y + m[0][2]) / w) as f32,
            ((m[1][0] * x + m[1][1] * y + m[1][2]) / w) as f32,
        )
    }

    /// Composes a quarter-turn rotation of tag coordinates: `self * R(quarter_turns * 90°)`.
    pub fn rotated(&self, quarter_turns: u8) -> Self {
        let (c, s) = match quarter_turns % 4 {
            0 => (1.0, 0.0),
            1 => (0.0, 1.0),
            2 => (-1.0, 0.0),
            _ => (0.0, -1.0),
        };
        let r = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]];
        let m = &self.0;
        Self(std::array::from_fn(|i| {
            std::array::from_fn(|j| (0..3).map(|k| m[i][k] * r[k][j]).sum())
        }))
    }

    /// The homography of a concentric square `scale` times the size.
    pub fn scaled(&self, scale: f64) -> Self {
        let mut m = self.0;
        for row in &mut m {
            row[0] *= scale;
            row[1] *= scale;
        }
        Self(m)
    }

    /// Approximate side of the black square in pixels.
    pub fn scale_estimate(&self) -> f32 {
        let c = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
            .map(|(x, y)| self.project(Vec2::new(x, y)));
        (0..4).map(|i| (c[(i + 1) % 4] - c[i]).length()).sum::<f32>() / 4.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lens_round_trips() {
        let lens = Lens {
            fx: 900.0,
            fy: 910.0,
            cx: 640.0,
            cy: 400.0,
            distortion: [-0.1, 0.03, 0.001, -0.002, 0.0],
        };
        for p in [Vec2::new(10.0, 20.0), Vec2::new(640.0, 400.0), Vec2::new(1270.0, 790.0)] {
            let q = lens.distort(lens.undistort(p));
            assert!((q - p).length() < 0.01, "{p:?} {q:?}");
        }
    }

    #[test]
    fn homography_maps_corners() {
        let corners = [
            Vec2::new(10.0, 20.0),
            Vec2::new(50.0, 22.0),
            Vec2::new(48.0, 70.0),
            Vec2::new(8.0, 60.0),
        ];
        let h = Homography::from_corners(&corners).unwrap();
        for (t, c) in [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)].iter().zip(corners) {
            let p = h.project(Vec2::new(t.0, t.1));
            assert!((p - c).length() < 1e-3, "{p:?} {c:?}");
        }
    }
}
