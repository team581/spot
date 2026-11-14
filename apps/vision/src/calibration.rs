//! ChArUco camera calibration through the OpenCV shim in `cpp/shim/charuco.cpp`.

use std::collections::BTreeSet;
use std::ffi::{CStr, c_char};

use nalgebra::{Matrix3, SMatrix, SVector, Vector3};

use serde::{Deserialize, Serialize};
use utoipa::{IntoParams, ToSchema};

use crate::config::Calibration;

/// Fewest captured views a solve accepts.
pub const MIN_FRAMES: usize = 12;
/// Fewest corners a captured view needs.
pub const MIN_CORNERS: usize = 8;
/// Largest RMS reprojection error, in pixels, of a calibration worth using.
pub const MAX_RMS: f64 = 1.0;
/// Most views a session captures.
pub const MAX_FRAMES: usize = 80;
/// Board movement since the last captured view, as a fraction of the image diagonal, needed
/// before another view is captured.
const MIN_MOTION: f64 = 0.025;
/// Coverage cells across and down the image.
const GRID: usize = 12;

/// A ChArUco board. Square and marker sizes are in meters.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, ToSchema, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct Board {
    pub squares_x: u32,
    pub squares_y: u32,
    pub square_size: f64,
    pub marker_size: f64,
    pub dictionary: Dictionary,
}

impl Default for Board {
    /// The board the team calibrates with.
    fn default() -> Self {
        Board {
            squares_x: 15,
            squares_y: 15,
            square_size: 0.03,
            marker_size: 0.022,
            dictionary: Dictionary::Aruco4x4_250,
        }
    }
}

/// OpenCV's predefined ArUco dictionaries.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
pub enum Dictionary {
    #[serde(rename = "4x4_50")]
    Aruco4x4_50 = 0,
    #[serde(rename = "4x4_100")]
    Aruco4x4_100 = 1,
    #[serde(rename = "4x4_250")]
    Aruco4x4_250 = 2,
    #[serde(rename = "5x5_50")]
    Aruco5x5_50 = 4,
    #[serde(rename = "5x5_100")]
    Aruco5x5_100 = 5,
    #[serde(rename = "6x6_50")]
    Aruco6x6_50 = 8,
    #[serde(rename = "6x6_250")]
    Aruco6x6_250 = 10,
}

/// Chessboard corners found in one image.
#[derive(Debug, Clone, Default, Serialize, ToSchema)]
pub struct View {
    pub ids: Vec<i32>,
    pub corners: Vec<[f32; 2]>,
}

#[derive(Debug, Clone, Serialize, ToSchema)]
pub struct Solution {
    pub calibration: Calibration,
    /// Views kept after outlier rejection, by capture index.
    pub used: Vec<usize>,
    /// Views rejected as outliers, by capture index.
    pub rejected: Vec<usize>,
    /// Whether the RMS error is within the threshold.
    pub accepted: bool,
}

/// How well the captured views cover the image.
#[derive(Debug, Clone, Default, Serialize, ToSchema)]
pub struct Coverage {
    /// Scores from 0 to 1 for a grid over the image, by row. An area scores 1 once it has
    /// enough views of the board at varied distances and tilts.
    pub cells: Vec<Vec<f64>>,
    /// Mean of the cell scores.
    pub progress: f64,
}

impl Coverage {
    /// Scores each area by how many distinct views of the board it has, and how much they
    /// vary in apparent size and tilt. Moving the board sideways or rolling it alone doesn't
    /// count as a new view.
    pub fn new(views: &[View], board: &Board, size: (u32, u32)) -> Self {
        // How far apart two views' signatures must be to count as distinct.
        let thresholds = [1.15f64.ln(), 0.12, 0.12, 0.12, 0.12];
        let mut seen: Vec<Vec<[f64; 5]>> = vec![Vec::new(); GRID * GRID];
        for view in views {
            let Some(signature) = signature(view, board, size) else { continue };
            let touched: BTreeSet<usize> =
                view.corners.iter().filter_map(|&p| cell(p, size)).collect();
            for i in touched {
                let distinct =
                    |old: &[f64; 5]| (0..5).any(|k| (signature[k] - old[k]).abs() >= thresholds[k]);
                if seen[i].iter().all(distinct) {
                    seen[i].push(signature);
                }
            }
        }
        let scores: Vec<f64> = seen
            .iter()
            .map(|signatures| {
                if signatures.is_empty() {
                    return 0.0;
                }
                let spread = |k: usize| {
                    let values = signatures.iter().map(|s| s[k]);
                    values.clone().fold(f64::MIN, f64::max) - values.fold(f64::MAX, f64::min)
                };
                let tilt = (1..5).map(spread).fold(0.0, f64::max);
                // Six distinct views, a 30% range in apparent size, and clear foreshortening.
                (signatures.len() as f64 / 6.0)
                    .min(spread(0) / 1.3f64.ln())
                    .min(tilt / 0.25)
                    .min(1.0)
            })
            .collect();
        Coverage {
            progress: scores.iter().sum::<f64>() / scores.len() as f64,
            cells: scores.chunks(GRID).map(<[f64]>::to_vec).collect(),
        }
    }

    /// Why the latest view isn't worth capturing, if it isn't.
    pub fn skip_reason(&self, latest: &View, frames: &[View], size: (u32, u32)) -> Option<String> {
        if latest.corners.len() < MIN_CORNERS {
            return Some("Show the board to the camera".into());
        }
        if frames.len() >= MAX_FRAMES {
            return Some(format!("Captured {MAX_FRAMES} views, the most a session keeps"));
        }
        let covered = latest
            .corners
            .iter()
            .filter(|&&p| cell(p, size).is_some_and(|i| self.cells[i / GRID][i % GRID] >= 1.0))
            .count();
        if covered as f64 > 0.9 * latest.corners.len() as f64 {
            return Some("This area is covered; move the board to yellow or empty areas".into());
        }
        if frames.last().is_some_and(|last| motion(latest, last, size) < MIN_MOTION) {
            return Some("Move or tilt the board for the next view".into());
        }
        None
    }
}

/// The coverage cell a pixel falls in.
fn cell([x, y]: [f32; 2], (width, height): (u32, u32)) -> Option<usize> {
    let (x, y) = (x as f64 / width as f64, y as f64 / height as f64);
    ((0.0..1.0).contains(&x) && (0.0..1.0).contains(&y))
        .then(|| (y * GRID as f64) as usize * GRID + (x * GRID as f64) as usize)
}

/// RMS movement of the corners two views share, as a fraction of the image diagonal. Views
/// sharing too few corners show different parts of the board, so count as far apart.
fn motion(a: &View, b: &View, (width, height): (u32, u32)) -> f64 {
    let moved: Vec<f64> = a
        .ids
        .iter()
        .zip(&a.corners)
        .filter_map(|(id, p)| {
            let q = b.corners[b.ids.iter().position(|other| other == id)?];
            Some(((p[0] - q[0]) as f64).powi(2) + ((p[1] - q[1]) as f64).powi(2))
        })
        .collect();
    if moved.len() < 4 {
        return f64::INFINITY;
    }
    (moved.iter().sum::<f64>() / moved.len() as f64).sqrt() / (width as f64).hypot(height as f64)
}

/// How the board looks in a view, regardless of where it is in the image: log apparent size,
/// log stretch, shear, and two perspective terms, from the homography's local shape at the
/// board's center. It needs no calibration and only guides capture.
fn signature(view: &View, board: &Board, size: (u32, u32)) -> Option<[f64; 5]> {
    let cols = board.squares_x as i32 - 1;
    // Normalize both axes by the same length so stretch keeps its meaning on nonsquare images.
    let scale = size.0.max(size.1) as f64;
    let points: Vec<([f64; 2], [f64; 2])> = view
        .ids
        .iter()
        .zip(&view.corners)
        .map(|(id, p)| {
            let board = [(id % cols + 1) as f64, (id / cols + 1) as f64];
            (board, [p[0] as f64 / scale, p[1] as f64 / scale])
        })
        .collect();
    // Corners on one line don't determine the board's shape.
    let n = points.len() as f64;
    let mean = points.iter().fold([0.0; 2], |m, (b, _)| [m[0] + b[0] / n, m[1] + b[1] / n]);
    let (mut sxx, mut syy, mut sxy) = (0.0, 0.0, 0.0);
    for ([x, y], _) in &points {
        let (dx, dy) = (x - mean[0], y - mean[1]);
        (sxx, syy, sxy) = (sxx + dx * dx, syy + dy * dy, sxy + dx * dy);
    }
    if points.len() < 4 || sxx * syy - sxy * sxy < 1e-6 * n * n {
        return None;
    }
    // Direct linear transform: the homography is the null vector of the stacked constraints.
    let mut normal = SMatrix::<f64, 9, 9>::zeros();
    for ([x, y], [u, v]) in &points {
        for row in [
            [*x, *y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, -u],
            [0.0, 0.0, 0.0, *x, *y, 1.0, -v * x, -v * y, -v],
        ] {
            let row = SVector::from(row);
            normal += row * row.transpose();
        }
    }
    let eigen = normal.symmetric_eigen();
    let h =
        Matrix3::from_iterator(eigen.eigenvectors.column(eigen.eigenvalues.imin()).iter().copied())
            .transpose();
    let center = h * Vector3::new(board.squares_x as f64 / 2.0, board.squares_y as f64 / 2.0, 1.0);
    if center.z.abs() < 1e-8 {
        return None;
    }
    let image = center.xy() / center.z;
    let perspective = h.fixed_view::<1, 2>(2, 0);
    let jacobian = (h.fixed_view::<2, 2>(0, 0) - image * perspective) / center.z;
    let (a, b) = (jacobian.column(0), jacobian.column(1));
    let (la, lb) = (a.norm(), b.norm());
    let area = jacobian.determinant().abs();
    if la.min(lb) < 1e-8 || area < 1e-10 {
        return None;
    }
    let squares = board.squares_x.max(board.squares_y) as f64;
    Some([
        area.sqrt().ln(),
        (la / lb).ln(),
        a.dot(&b) / (la * lb),
        perspective[0] / center.z * squares,
        perspective[1] / center.z * squares,
    ])
}

#[repr(C)]
struct Raw {
    _private: [u8; 0],
}

unsafe extern "C" {
    fn spot_charuco_new(
        squares_x: i32,
        squares_y: i32,
        square_size: f64,
        marker_size: f64,
        dictionary: i32,
        error: *mut c_char,
        len: i32,
    ) -> *mut Raw;
    fn spot_charuco_free(raw: *mut Raw);
    fn spot_charuco_detect(
        raw: *mut Raw,
        gray: *const u8,
        width: i32,
        height: i32,
        corners: *mut f32,
        ids: *mut i32,
        capacity: i32,
        error: *mut c_char,
        len: i32,
    ) -> i32;
    fn spot_charuco_image(
        raw: *mut Raw,
        pixels_per_square: i32,
        png: *mut *mut u8,
        png_len: *mut usize,
        error: *mut c_char,
        len: i32,
    ) -> i32;
    fn spot_charuco_free_buffer(buffer: *mut u8);
    #[allow(clippy::too_many_arguments)]
    fn spot_charuco_calibrate(
        raw: *mut Raw,
        frames: i32,
        counts: *const i32,
        ids: *const i32,
        corners: *const f32,
        width: i32,
        height: i32,
        camera: *mut f64,
        distortion: *mut f64,
        view_errors: *mut f64,
        rms: *mut f64,
        error: *mut c_char,
        len: i32,
    ) -> i32;
}

fn message(buffer: &[c_char]) -> String {
    // SAFETY: the shim NUL-terminates within the zeroed buffer.
    unsafe { CStr::from_ptr(buffer.as_ptr()) }.to_string_lossy().into_owned()
}

pub struct Charuco {
    raw: *mut Raw,
    board: Board,
}

// SAFETY: the OpenCV board and detector are only used behind `&mut self`.
unsafe impl Send for Charuco {}

impl Charuco {
    pub fn new(board: &Board) -> Result<Self, String> {
        if !(board.marker_size > 0.0 && board.marker_size < board.square_size)
            || board.squares_x < 3
            || board.squares_y < 3
        {
            return Err("Use at least 3x3 squares, with markers smaller than squares".into());
        }
        let mut error = [0 as c_char; 256];
        // SAFETY: the error buffer outlives the call and its length is passed.
        let raw = unsafe {
            spot_charuco_new(
                board.squares_x as i32,
                board.squares_y as i32,
                board.square_size,
                board.marker_size,
                board.dictionary as i32,
                error.as_mut_ptr(),
                255,
            )
        };
        if raw.is_null() {
            return Err(format!("ChArUco board: {}", message(&error)));
        }
        Ok(Charuco { raw, board: board.clone() })
    }

    pub fn detect(&mut self, gray: &[u8], width: u32, height: u32) -> Result<View, String> {
        assert_eq!(gray.len(), (width * height) as usize);
        let capacity = ((self.board.squares_x - 1) * (self.board.squares_y - 1)) as usize;
        let mut corners = vec![[0f32; 2]; capacity];
        let mut ids = vec![0i32; capacity];
        let mut error = [0 as c_char; 256];
        // SAFETY: the image has the given size and the outputs hold `capacity` entries.
        let count = unsafe {
            spot_charuco_detect(
                self.raw,
                gray.as_ptr(),
                width as i32,
                height as i32,
                corners.as_mut_ptr().cast(),
                ids.as_mut_ptr(),
                capacity as i32,
                error.as_mut_ptr(),
                255,
            )
        };
        if count < 0 {
            return Err(message(&error));
        }
        corners.truncate(count as usize);
        ids.truncate(count as usize);
        Ok(View { ids, corners })
    }

    /// A PNG of the board, to check the geometry against a physical board.
    pub fn png(&mut self) -> Result<Vec<u8>, String> {
        const PIXELS_PER_SQUARE: i32 = 200;
        let (mut png, mut len) = (std::ptr::null_mut(), 0);
        let mut error = [0 as c_char; 256];
        // SAFETY: the outputs are written on success and freed below.
        let status = unsafe {
            spot_charuco_image(
                self.raw,
                PIXELS_PER_SQUARE,
                &mut png,
                &mut len,
                error.as_mut_ptr(),
                255,
            )
        };
        if status != 0 {
            return Err(message(&error));
        }
        // SAFETY: the shim allocated `len` bytes at `png`.
        let bytes = unsafe { std::slice::from_raw_parts(png, len) }.to_vec();
        unsafe { spot_charuco_free_buffer(png) };
        Ok(bytes)
    }

    /// Calibrates, then drops views more than three scaled MADs above the median error and
    /// refits once.
    pub fn solve(&mut self, views: &[View], size: (u32, u32)) -> Result<Solution, String> {
        if views.len() < MIN_FRAMES {
            return Err(format!("Capture at least {MIN_FRAMES} views"));
        }
        let all: Vec<usize> = (0..views.len()).collect();
        let (calibration, errors) = self.calibrate(views, &all, size)?;
        let median = median(&errors);
        let mad = median_abs(&errors, median);
        let limit = median + 3.0 * 1.4826 * mad;
        let (used, rejected): (Vec<usize>, Vec<usize>) =
            all.iter().partition(|&&i| errors[i] <= limit);
        let calibration = if rejected.is_empty() || used.len() < 4 {
            calibration
        } else {
            self.calibrate(views, &used, size)?.0
        };
        let accepted = calibration.rms.is_some_and(|rms| rms <= MAX_RMS);
        Ok(Solution { calibration, used, rejected, accepted })
    }

    fn calibrate(
        &mut self,
        views: &[View],
        use_views: &[usize],
        size: (u32, u32),
    ) -> Result<(Calibration, Vec<f64>), String> {
        let selected: Vec<&View> = use_views.iter().map(|&i| &views[i]).collect();
        let counts: Vec<i32> = selected.iter().map(|v| v.ids.len() as i32).collect();
        let ids: Vec<i32> = selected.iter().flat_map(|v| v.ids.iter().copied()).collect();
        let corners: Vec<f32> =
            selected.iter().flat_map(|v| v.corners.iter().flatten().copied()).collect();
        let (mut camera, mut distortion, mut rms) = ([0.0; 9], [0.0; 5], 0.0);
        let mut view_errors = vec![0.0; selected.len()];
        let mut error = [0 as c_char; 256];
        // SAFETY: inputs are packed as documented by the shim; outputs have the sizes it writes.
        let status = unsafe {
            spot_charuco_calibrate(
                self.raw,
                selected.len() as i32,
                counts.as_ptr(),
                ids.as_ptr(),
                corners.as_ptr(),
                size.0 as i32,
                size.1 as i32,
                camera.as_mut_ptr(),
                distortion.as_mut_ptr(),
                view_errors.as_mut_ptr(),
                &mut rms,
                error.as_mut_ptr(),
                255,
            )
        };
        if status != 0 {
            return Err(format!("Calibration failed: {}", message(&error)));
        }
        let mut errors = vec![0.0; views.len()];
        for (&i, e) in use_views.iter().zip(view_errors) {
            errors[i] = e;
        }
        let calibration = Calibration {
            fx: camera[0],
            fy: camera[4],
            cx: camera[2],
            cy: camera[5],
            distortion,
            rms: Some(rms),
        };
        Ok((calibration, errors))
    }
}

impl Drop for Charuco {
    fn drop(&mut self) {
        // SAFETY: created by `spot_charuco_new` and freed once.
        unsafe { spot_charuco_free(self.raw) }
    }
}

fn median(values: &[f64]) -> f64 {
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    let n = sorted.len();
    if n % 2 == 1 { sorted[n / 2] } else { (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0 }
}

fn median_abs(values: &[f64], center: f64) -> f64 {
    median(&values.iter().map(|v| (v - center).abs()).collect::<Vec<_>>())
}

#[cfg(test)]
mod tests {
    use super::*;

    const SIZE: (u32, u32) = (1280, 800);

    /// Projects the board's corners through a pinhole camera, keeping those in the image.
    /// Detection is exercised on real images on the Jetson; these tests check the math.
    fn project(
        board: &Board,
        (fx, fy, cx, cy): (f64, f64, f64, f64),
        rotation: nalgebra::Rotation3<f64>,
        position: nalgebra::Vector3<f64>,
    ) -> View {
        let s = board.square_size;
        let mut view = View::default();
        for row in 0..board.squares_y - 1 {
            for col in 0..board.squares_x - 1 {
                let local = nalgebra::Vector3::new(
                    (col as f64 + 1.0 - board.squares_x as f64 / 2.0) * s,
                    (row as f64 + 1.0 - board.squares_y as f64 / 2.0) * s,
                    0.0,
                );
                let p = rotation * local + position;
                let (u, v) = (fx * p.x / p.z + cx, fy * p.y / p.z + cy);
                if (0.0..SIZE.0 as f64).contains(&u) && (0.0..SIZE.1 as f64).contains(&v) {
                    // OpenCV numbers chessboard corners row-major from the board origin.
                    view.ids.push((row * (board.squares_x - 1) + col) as i32);
                    view.corners.push([u as f32, v as f32]);
                }
            }
        }
        view
    }

    /// Checks that calibration recovers a known camera from synthetic views.
    #[test]
    fn calibrates_synthetic_views() {
        let board = Board::default();
        let mut charuco = Charuco::new(&board).unwrap();
        let (fx, fy, cx, cy) = (900.0, 905.0, 640.0, 400.0);
        let mut views = Vec::new();
        for i in 0..16 {
            let angle = (i as f64) * 0.35;
            let (tilt_x, tilt_y) = (0.4 * angle.sin(), 0.4 * angle.cos());
            let distance = 0.35 + 0.02 * (i % 4) as f64;
            let rotation = nalgebra::Rotation3::from_euler_angles(tilt_x, tilt_y, 0.1 * angle);
            let mut view = project(
                &board,
                (fx, fy, cx, cy),
                rotation,
                nalgebra::Vector3::new(0.0, 0.0, distance),
            );
            if i == 5 {
                // Corrupt one view to exercise outlier rejection.
                for (id, corner) in view.ids.iter().zip(&mut view.corners) {
                    let offset = 6.0 * ((id % 3) as f32 - 1.0);
                    *corner = [corner[0] + offset, corner[1] - offset];
                }
            }
            views.push(view);
        }
        // Board coordinates in OpenCV start at a corner, not the center; the offset only
        // changes extrinsics.
        let solution = charuco.solve(&views, SIZE).unwrap();
        let k = &solution.calibration;
        assert!(solution.rejected.contains(&5), "{solution:?}");
        assert!((k.fx - fx).abs() < 2.0 && (k.fy - fy).abs() < 2.0, "{k:?}");
        assert!((k.cx - cx).abs() < 2.0 && (k.cy - cy).abs() < 2.0, "{k:?}");
        assert!(solution.accepted, "{k:?}");
    }

    /// Sliding a flat board around the image adds no coverage; varying its distance and tilt
    /// does.
    #[test]
    fn coverage_needs_varied_distances_and_tilts() {
        let board = Board::default();
        let camera = (900.0, 900.0, 640.0, 400.0);
        let flat = nalgebra::Rotation3::identity();
        let mut views = Vec::new();
        for x in [-0.15, 0.0, 0.15] {
            for y in [-0.1, 0.0, 0.1] {
                views.push(project(&board, camera, flat, nalgebra::Vector3::new(x, y, 0.6)));
            }
        }
        let coverage = Coverage::new(&views, &board, SIZE);
        assert_eq!(coverage.progress, 0.0);
        assert!(coverage.skip_reason(&views[8], &views, SIZE).unwrap().starts_with("Move"));

        for distance in [0.5, 0.6, 0.75] {
            for (tilt_x, tilt_y) in [(0.0, 0.0), (0.5, 0.0), (-0.5, 0.0), (0.0, 0.5), (0.0, -0.5)] {
                let rotation = nalgebra::Rotation3::from_euler_angles(tilt_x, tilt_y, 0.0);
                let position = nalgebra::Vector3::new(0.0, 0.0, distance);
                views.push(project(&board, camera, rotation, position));
            }
        }
        let coverage = Coverage::new(&views, &board, SIZE);
        assert_eq!(coverage.cells[GRID / 2][GRID / 2], 1.0, "{coverage:?}");
        let center = project(&board, camera, flat, nalgebra::Vector3::new(0.0, 0.0, 1.6));
        assert!(coverage.skip_reason(&center, &views, SIZE).unwrap().contains("covered"));
    }

    #[test]
    fn detects_every_corner_of_a_rendered_board() {
        let board = Board::default();
        let mut charuco = Charuco::new(&board).unwrap();
        let png = charuco.png().unwrap();
        let image = image::load_from_memory(&png).unwrap().to_luma8();
        // Detection needs a quiet zone around the board.
        let margin = 60;
        let (width, height) = (image.width() + 2 * margin, image.height() + 2 * margin);
        let mut padded = image::GrayImage::from_pixel(width, height, image::Luma([255]));
        image::imageops::overlay(&mut padded, &image, margin.into(), margin.into());
        let view = charuco.detect(padded.as_raw(), width, height).unwrap();
        assert_eq!(view.ids.len(), ((board.squares_x - 1) * (board.squares_y - 1)) as usize);
    }
}
