//! JPEG to grayscale. Jetson builds decode on the NVJPG engine.

use zune_core::bytestream::ZCursor;
use zune_core::colorspace::ColorSpace;
use zune_core::options::DecoderOptions;
use zune_jpeg::JpegDecoder;

pub struct Gray {
    pub pixels: Vec<u8>,
    pub width: u32,
    pub height: u32,
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
        Ok(Gray { pixels, width: info.width.into(), height: info.height.into() })
    }
}

#[cfg(feature = "jetson")]
pub use nvjpg::Decoder;

#[cfg(feature = "jetson")]
mod nvjpg {
    use std::ffi::{CStr, c_char};

    use super::Gray;

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
            out: *mut u8,
            capacity: usize,
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
            let (width, height) = super::dimensions(jpeg)?;
            let mut pixels = vec![0; (width * height) as usize];
            let (mut w, mut h) = (0, 0);
            let mut error = [0 as c_char; 256];
            // SAFETY: all buffers outlive the call and their lengths are passed.
            let status = unsafe {
                spot_nvjpg_decode(
                    self.0,
                    jpeg.as_ptr(),
                    jpeg.len(),
                    pixels.as_mut_ptr(),
                    pixels.len(),
                    &mut w,
                    &mut h,
                    error.as_mut_ptr(),
                    255,
                )
            };
            // SAFETY: the shim NUL-terminates within the zeroed buffer.
            let message =
                || unsafe { CStr::from_ptr(error.as_ptr()) }.to_string_lossy().into_owned();
            anyhow::ensure!(status == 0, "NVJPG: {}", message());
            anyhow::ensure!(
                (w, h) == (width, height),
                "NVJPG returned {w}x{h} for {width}x{height}"
            );
            Ok(Gray { pixels, width, height })
        }
    }

    impl Drop for Decoder {
        fn drop(&mut self) {
            // SAFETY: created by `spot_nvjpg_new` and freed once.
            unsafe { spot_nvjpg_free(self.0) }
        }
    }
}
