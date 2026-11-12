//! JPEG to grayscale. Jetson builds decode on the NVJPG engine.

use zune_core::bytestream::ZCursor;
#[cfg(not(feature = "jetson"))]
use zune_core::colorspace::ColorSpace;
#[cfg(not(feature = "jetson"))]
use zune_core::options::DecoderOptions;
use zune_jpeg::JpegDecoder;

pub struct Gray {
    pub pixels: Pixels,
    pub width: u32,
    pub height: u32,
}

/// Where a decoded image's 8-bit luma lives.
pub enum Pixels {
    /// Packed rows in CPU memory.
    #[cfg_attr(feature = "jetson", allow(dead_code))]
    Host(Vec<u8>),
    /// Rows `pitch` bytes apart in CUDA device memory, valid until the next decode.
    #[cfg_attr(not(feature = "jetson"), allow(dead_code))]
    Device { ptr: *const u8, pitch: usize },
}

pub fn dimensions(jpeg: &[u8]) -> anyhow::Result<(u32, u32)> {
    let mut decoder = JpegDecoder::new(ZCursor::new(jpeg));
    decoder.decode_headers()?;
    let info = decoder.info().ok_or_else(|| anyhow::anyhow!("missing JPEG header"))?;
    Ok((info.width.into(), info.height.into()))
}

#[cfg(not(feature = "jetson"))]
pub struct Decoder;

#[cfg(not(feature = "jetson"))]
impl Decoder {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Decoder)
    }

    pub fn decode(&mut self, jpeg: &[u8]) -> anyhow::Result<Gray> {
        let options = DecoderOptions::default().jpeg_set_out_colorspace(ColorSpace::Luma);
        let mut decoder = JpegDecoder::new_with_options(ZCursor::new(jpeg), options);
        let pixels = decoder.decode()?;
        let info = decoder.info().ok_or_else(|| anyhow::anyhow!("missing JPEG header"))?;
        Ok(Gray {
            pixels: Pixels::Host(pixels),
            width: info.width.into(),
            height: info.height.into(),
        })
    }
}

#[cfg(feature = "jetson")]
pub use nvjpg::Decoder;

#[cfg(feature = "jetson")]
mod nvjpg {
    use std::ffi::{CStr, c_char};

    use super::{Gray, Pixels};

    #[repr(C)]
    struct Raw {
        _private: [u8; 0],
    }

    unsafe extern "C" {
        fn spot_nvjpg_new() -> *mut Raw;
        fn spot_nvjpg_decode(
            decoder: *mut Raw,
            jpeg: *const u8,
            len: usize,
            luma: *mut *const u8,
            pitch: *mut u32,
            width: *mut u32,
            height: *mut u32,
            error: *mut c_char,
            error_len: i32,
        ) -> i32;
        fn spot_nvjpg_free(decoder: *mut Raw);
    }

    pub struct Decoder(*mut Raw);

    // SAFETY: a decoder is only used by one thread at a time.
    unsafe impl Send for Decoder {}

    impl Decoder {
        pub fn new() -> anyhow::Result<Self> {
            // SAFETY: no preconditions.
            let raw = unsafe { spot_nvjpg_new() };
            anyhow::ensure!(!raw.is_null(), "NVJPG decoder unavailable");
            Ok(Decoder(raw))
        }

        pub fn decode(&mut self, jpeg: &[u8]) -> anyhow::Result<Gray> {
            // UVC cameras may pad frames after the end-of-image marker, which NVJPG's
            // libjpeg reports on every frame.
            let end =
                jpeg.windows(2).rposition(|m| m == [0xff, 0xd9]).map_or(jpeg.len(), |i| i + 2);
            let jpeg = &jpeg[..end];
            let (mut luma, mut pitch, mut width, mut height) = (std::ptr::null(), 0, 0, 0);
            let mut error = [0 as c_char; 256];
            // SAFETY: all outputs outlive the call and the error length is passed.
            let status = unsafe {
                spot_nvjpg_decode(
                    self.0,
                    jpeg.as_ptr(),
                    jpeg.len(),
                    &mut luma,
                    &mut pitch,
                    &mut width,
                    &mut height,
                    error.as_mut_ptr(),
                    255,
                )
            };
            // SAFETY: the shim NUL-terminates within the zeroed buffer.
            let message =
                || unsafe { CStr::from_ptr(error.as_ptr()) }.to_string_lossy().into_owned();
            anyhow::ensure!(status == 0, "NVJPG: {}", message());
            Ok(Gray { pixels: Pixels::Device { ptr: luma, pitch: pitch as usize }, width, height })
        }
    }

    impl Drop for Decoder {
        fn drop(&mut self) {
            // SAFETY: created by `spot_nvjpg_new` and freed once.
            unsafe { spot_nvjpg_free(self.0) }
        }
    }
}
