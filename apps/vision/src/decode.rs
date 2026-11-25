//! JPEG to grayscale. CPU decoding lets cameras decode in parallel without waiting
//! on the shared NVJPG engine.

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

pub fn decode(jpeg: &[u8]) -> anyhow::Result<Gray> {
    let options = DecoderOptions::default().jpeg_set_out_colorspace(ColorSpace::Luma);
    let mut decoder = JpegDecoder::new_with_options(ZCursor::new(jpeg), options);
    let pixels = decoder.decode()?;
    let info = decoder.info().ok_or_else(|| anyhow::anyhow!("missing JPEG header"))?;
    Ok(Gray { pixels, width: info.width.into(), height: info.height.into() })
}
