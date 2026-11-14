//! ChArUco camera calibration through the OpenCV shim in `cpp/shim/charuco.cpp`.

use std::ffi::{CStr, c_char};

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use crate::config::Calibration;

/// Fewest captured views a solve accepts.
pub const MIN_FRAMES: usize = 12;
/// Fewest corners a captured view needs.
pub const MIN_CORNERS: usize = 8;
/// Largest RMS reprojection error, in pixels, of a calibration worth using.
pub const MAX_RMS: f64 = 1.0;

/// A ChArUco board. Square and marker sizes are in meters.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, ToSchema)]
pub struct Board {
    pub squares_x: u32,
    pub squares_y: u32,
    pub square_size: f64,
    pub marker_size: f64,
    pub dictionary: Dictionary,
}

impl Default for Board {
    /// Fits on Letter and A4 paper.
    fn default() -> Self {
        Board {
            squares_x: 11,
            squares_y: 8,
            square_size: 0.02,
            marker_size: 0.015,
            dictionary: Dictionary::Aruco5x5_100,
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

    /// A printable SVG of the board at true size, with a scale check.
    pub fn svg(&mut self) -> Result<String, String> {
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
        let b = &self.board;
        let (width, height) =
            (b.squares_x as f64 * b.square_size * 1e3, b.squares_y as f64 * b.square_size * 1e3);
        let margin = 10.0;
        let caption = format!(
            "{}x{} squares of {:.1} mm, {:.1} mm {} markers. Print at 100% and measure a square.",
            b.squares_x,
            b.squares_y,
            b.square_size * 1e3,
            b.marker_size * 1e3,
            serde_json::to_value(b.dictionary).unwrap().as_str().unwrap_or_default(),
        );
        Ok(format!(
            r#"<svg xmlns="http://www.w3.org/2000/svg" width="{pw}mm" height="{ph}mm" viewBox="0 0 {pw} {ph}"><rect width="100%" height="100%" fill="white"/><image x="{margin}" y="{margin}" width="{width}" height="{height}" style="image-rendering:pixelated" href="data:image/png;base64,{data}"/><text x="{margin}" y="{ty}" font-family="sans-serif" font-size="4">{caption}</text></svg>"#,
            pw = width + 2.0 * margin,
            ph = height + 2.0 * margin + 6.0,
            ty = height + margin + 7.0,
            data = base64(&bytes),
        ))
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

fn base64(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let n = (chunk[0] as u32) << 16
            | (*chunk.get(1).unwrap_or(&0) as u32) << 8
            | *chunk.get(2).unwrap_or(&0) as u32;
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(TABLE[(n >> (18 - 6 * i) & 63) as usize] as char);
            } else {
                out.push('=');
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Renders the board, warps it into synthetic views with a known camera, and checks
    /// that detection and calibration recover the camera.
    #[test]
    fn calibrates_synthetic_views() {
        let board = Board::default();
        let mut charuco = Charuco::new(&board).unwrap();
        let svg = charuco.svg().unwrap();
        assert!(svg.starts_with("<svg"));

        // Project the board's corners directly: detection is exercised on real images on
        // the Jetson, this checks the calibration and outlier rejection plumbing.
        let (fx, fy, cx, cy) = (900.0, 905.0, 640.0, 400.0);
        let s = board.square_size;
        let mut views = Vec::new();
        for i in 0..16 {
            let angle = (i as f64) * 0.35;
            let (tilt_x, tilt_y) = (0.4 * angle.sin(), 0.4 * angle.cos());
            let distance = 0.35 + 0.02 * (i % 4) as f64;
            let rotation = nalgebra::Rotation3::from_euler_angles(tilt_x, tilt_y, 0.1 * angle);
            let mut view = View::default();
            for row in 0..board.squares_y - 1 {
                for col in 0..board.squares_x - 1 {
                    let local = nalgebra::Vector3::new(
                        (col as f64 + 1.0 - board.squares_x as f64 / 2.0) * s,
                        (row as f64 + 1.0 - board.squares_y as f64 / 2.0) * s,
                        0.0,
                    );
                    let p = rotation * local + nalgebra::Vector3::new(0.0, 0.0, distance);
                    let (u, v) = (fx * p.x / p.z + cx, fy * p.y / p.z + cy);
                    // OpenCV numbers chessboard corners row-major from the board origin.
                    let id = row * (board.squares_x - 1) + col;
                    // Corrupt one view to exercise outlier rejection.
                    let offset = if i == 5 { 6.0 * ((id % 3) as f64 - 1.0) } else { 0.0 };
                    view.ids.push(id as i32);
                    view.corners.push([(u + offset) as f32, (v - offset) as f32]);
                }
            }
            views.push(view);
        }
        // Board coordinates in OpenCV start at a corner, not the center; the offset only
        // changes extrinsics.
        let solution = charuco.solve(&views, (1280, 800)).unwrap();
        let k = &solution.calibration;
        assert!(solution.rejected.contains(&5), "{solution:?}");
        assert!((k.fx - fx).abs() < 2.0 && (k.fy - fy).abs() < 2.0, "{k:?}");
        assert!((k.cx - cx).abs() < 2.0 && (k.cy - cy).abs() < 2.0, "{k:?}");
        assert!(solution.accepted, "{k:?}");
    }

    #[test]
    fn detects_every_corner_of_a_rendered_board() {
        let board = Board::default();
        let mut charuco = Charuco::new(&board).unwrap();
        let svg = charuco.svg().unwrap();
        let data = svg.split("base64,").nth(1).unwrap().split('"').next().unwrap();
        let png = decode_base64(data);
        let image = image::load_from_memory(&png).unwrap().to_luma8();
        // Detection needs a quiet zone around the board.
        let margin = 60;
        let (width, height) = (image.width() + 2 * margin, image.height() + 2 * margin);
        let mut padded = image::GrayImage::from_pixel(width, height, image::Luma([255]));
        image::imageops::overlay(&mut padded, &image, margin.into(), margin.into());
        let view = charuco.detect(padded.as_raw(), width, height).unwrap();
        assert_eq!(view.ids.len(), ((board.squares_x - 1) * (board.squares_y - 1)) as usize);
    }

    fn decode_base64(text: &str) -> Vec<u8> {
        let value = |c: u8| match c {
            b'A'..=b'Z' => c - b'A',
            b'a'..=b'z' => c - b'a' + 26,
            b'0'..=b'9' => c - b'0' + 52,
            b'+' => 62,
            _ => 63,
        } as u32;
        let bytes: Vec<u8> = text.bytes().filter(|&c| c != b'=').collect();
        let mut out = Vec::new();
        for chunk in bytes.chunks(4) {
            let n = chunk.iter().enumerate().fold(0, |n, (i, &c)| n | value(c) << (18 - 6 * i));
            out.extend_from_slice(&n.to_be_bytes()[1..chunk.len()]);
        }
        out
    }

    #[test]
    fn base64_round_trips() {
        for bytes in [&b"M"[..], b"Ma", b"Man", b"Many bytes"] {
            assert_eq!(decode_base64(&base64(bytes)), bytes);
        }
        assert_eq!(base64(b"Ma"), "TWE=");
    }
}
