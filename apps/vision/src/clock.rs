/// Microseconds on `CLOCK_MONOTONIC`, the clock V4L2 uses for buffer timestamps.
pub fn monotonic_us() -> i64 {
    let mut now = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: `now` is a valid timespec and CLOCK_MONOTONIC is always available.
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut now) };
    now.tv_sec * 1_000_000 + now.tv_nsec / 1_000
}
