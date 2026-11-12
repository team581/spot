//! A borrowed 8-bit grayscale image.

use super::geometry::Vec2;

#[derive(Clone, Copy)]
pub struct ImageView<'a> {
    pub data: &'a [u8],
    pub width: usize,
    pub height: usize,
    /// Bytes between rows.
    pub stride: usize,
}

impl<'a> ImageView<'a> {
    pub fn new(data: &'a [u8], width: usize, height: usize, stride: usize) -> Option<Self> {
        let needed = if height == 0 { 0 } else { (height - 1) * stride + width };
        (stride >= width && data.len() >= needed).then_some(Self { data, width, height, stride })
    }

    pub fn row(&self, y: usize) -> &'a [u8] {
        &self.data[y * self.stride..y * self.stride + self.width]
    }

    /// Bilinear sample with pixel centres at integer coordinates, or `None` outside the image.
    #[inline]
    pub fn bilinear(&self, p: Vec2) -> Option<f32> {
        let (x, y) = (p.x, p.y);
        if !(x >= 0.0 && y >= 0.0 && x < (self.width - 1) as f32 && y < (self.height - 1) as f32) {
            return None;
        }
        let (x0, y0) = (x as usize, y as usize);
        let (fx, fy) = (x - x0 as f32, y - y0 as f32);
        let i = y0 * self.stride + x0;
        // SAFETY: x0 + 1 < width and y0 + 1 < height were checked above, and the constructor
        // checked that the data covers every row.
        let (a, b, c, d) = unsafe {
            (
                *self.data.get_unchecked(i) as f32,
                *self.data.get_unchecked(i + 1) as f32,
                *self.data.get_unchecked(i + self.stride) as f32,
                *self.data.get_unchecked(i + self.stride + 1) as f32,
            )
        };
        let top = a + (b - a) * fx;
        let bottom = c + (d - c) * fx;
        Some(top + (bottom - top) * fy)
    }
}
