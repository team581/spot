//! The dense stage on the GPU (`cpp/shim/dense.cu`).

use std::ffi::{CStr, c_char};

use super::dense::Level;

#[repr(C)]
struct RawLevel {
    width: i32,
    height: i32,
}

#[repr(C)]
struct Raw {
    _private: [u8; 0],
}

unsafe extern "C" {
    fn spot_dense_new(
        width: i32,
        height: i32,
        step: i32,
        min_contrast: i32,
        noise_factor: i32,
        levels: *const RawLevel,
        count: i32,
        error: *mut c_char,
        len: i32,
    ) -> *mut Raw;
    fn spot_dense_upload(dense: *mut Raw, image: *const u8) -> *const u8;
    fn spot_dense_run(
        dense: *mut Raw,
        gray: *const u8,
        pitch: i32,
        masks: *mut *const u32,
        image: *mut *const u8,
        error: *mut c_char,
        len: i32,
    ) -> i32;
    fn spot_dense_free(dense: *mut Raw);
}

fn message(buffer: &[c_char]) -> String {
    // SAFETY: the shim NUL-terminates within the buffer, which starts zeroed.
    unsafe { CStr::from_ptr(buffer.as_ptr()) }.to_string_lossy().into_owned()
}

pub struct Gpu {
    raw: *mut Raw,
    width: usize,
    height: usize,
    /// Each level's offset and length in the shim's mask buffer, in words.
    spans: Vec<(usize, usize)>,
    masks: *const u32,
    image: *const u8,
}

// SAFETY: the shim's state is only used through `&mut self`, from one thread at a time.
unsafe impl Send for Gpu {}

impl Gpu {
    pub fn new(
        width: usize,
        height: usize,
        step: usize,
        min_contrast: u8,
        noise_factor: u32,
        levels: &[Level],
    ) -> anyhow::Result<Self> {
        let raw_levels: Vec<RawLevel> = levels
            .iter()
            .map(|l| RawLevel { width: l.width as i32, height: l.height as i32 })
            .collect();
        let mut error = [0 as c_char; 256];
        // SAFETY: the levels and error buffer outlive the call, and their lengths are passed.
        let raw = unsafe {
            spot_dense_new(
                width as i32,
                height as i32,
                step as i32,
                min_contrast.into(),
                noise_factor as i32,
                raw_levels.as_ptr(),
                raw_levels.len() as i32,
                error.as_mut_ptr(),
                255,
            )
        };
        anyhow::ensure!(!raw.is_null(), "GPU detector: {}", message(&error));
        let mut offset = 0;
        let spans = levels
            .iter()
            .map(|l| {
                let len = l.words() * l.height;
                offset += len;
                (offset - len, len)
            })
            .collect();
        Ok(Self { raw, width, height, spans, masks: std::ptr::null(), image: std::ptr::null() })
    }

    /// Copies a packed host image to device memory, returning a pointer valid until the next
    /// upload.
    pub fn upload(&mut self, image: &[u8]) -> anyhow::Result<*const u8> {
        anyhow::ensure!(image.len() == self.width * self.height, "image size mismatch");
        // SAFETY: the image covers the detector's size.
        let device = unsafe { spot_dense_upload(self.raw, image.as_ptr()) };
        anyhow::ensure!(!device.is_null(), "could not upload the image");
        Ok(device)
    }

    /// Runs on a device image with the detector's size and rows `pitch` bytes apart.
    ///
    /// # Safety
    /// `gray` must point to such an image in device memory.
    pub unsafe fn run(&mut self, gray: *const u8, pitch: usize) -> anyhow::Result<()> {
        let mut error = [0 as c_char; 256];
        // SAFETY: the caller guarantees the image; the outputs outlive the call.
        let status = unsafe {
            spot_dense_run(
                self.raw,
                gray,
                pitch as i32,
                &mut self.masks,
                &mut self.image,
                error.as_mut_ptr(),
                255,
            )
        };
        anyhow::ensure!(status == 0, "GPU detector: {}", message(&error));
        Ok(())
    }

    /// A level's mask from the last run.
    pub fn mask(&self, level: usize) -> &[u32] {
        let (offset, len) = self.spans[level];
        // SAFETY: the shim's pinned mask buffer holds every level and stays valid until the
        // next run, which needs `&mut self`.
        unsafe { std::slice::from_raw_parts(self.masks.add(offset), len) }
    }

    /// The last run's image as packed host memory.
    pub fn image(&self) -> &[u8] {
        // SAFETY: as for `mask`.
        unsafe { std::slice::from_raw_parts(self.image, self.width * self.height) }
    }
}

impl Drop for Gpu {
    fn drop(&mut self) {
        // SAFETY: `raw` came from `spot_dense_new` and is freed once.
        unsafe { spot_dense_free(self.raw) }
    }
}

#[cfg(test)]
mod tests {
    use super::super::dense::{self, Cpu};
    use super::super::image::ImageView;
    use super::*;

    /// The GPU's bits must match the CPU reference exactly, including under noise.
    #[test]
    fn matches_the_cpu() {
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/regression");
        for name in ["center.jpg", "multi.jpg", "rotated.jpg", "blank.jpg"] {
            let image = ::image::open(format!("{dir}/{name}")).unwrap().to_luma8();
            let (w, h) = (image.width() as usize, image.height() as usize);
            let mut pixels = image.into_raw();
            for noisy in [false, true] {
                if noisy {
                    let mut seed = 12345u32;
                    for p in &mut pixels {
                        seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12345);
                        *p = p.saturating_add_signed(((seed >> 16) % 41) as i8 - 20);
                    }
                }
                let levels = dense::layout(w, h, 3);
                let mut cpu = Cpu::default();
                cpu.run(&ImageView::new(&pixels, w, h, w).unwrap(), &levels, 3, 20, 6);
                let mut gpu = Gpu::new(w, h, 3, 20, 6, &levels).unwrap();
                let device = gpu.upload(&pixels).unwrap();
                unsafe { gpu.run(device, w).unwrap() };
                assert_eq!(gpu.image(), &pixels[..]);
                for k in 0..levels.len() {
                    let differing =
                        cpu.masks.levels[k].iter().zip(gpu.mask(k)).filter(|(a, b)| a != b).count();
                    assert_eq!(differing, 0, "{name} noisy={noisy} level {k}");
                }
            }
        }
    }
}
