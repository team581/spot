//! CPU, memory, GPU, and temperature readings from procfs and sysfs.

use std::sync::Mutex;

use serde::Serialize;
use utoipa::ToSchema;

#[derive(Serialize, ToSchema)]
pub struct SystemStatus {
    /// CPU use since the previous reading.
    pub cpu_percent: Option<f64>,
    pub memory_percent: Option<f64>,
    /// Jetson GPU load.
    pub gpu_percent: Option<f64>,
    pub disk_percent: Option<f64>,
    pub temperatures: Vec<Temperature>,
    pub uptime_s: Option<f64>,
}

#[derive(Serialize, ToSchema)]
pub struct Temperature {
    pub name: String,
    pub celsius: f64,
}

const GPU_LOAD: &str = "/sys/devices/platform/bus@0/17000000.gpu/load";

/// Keeps the previous CPU counters to report use between readings.
#[derive(Default)]
pub struct System(Mutex<Option<(u64, u64)>>);

fn read(path: &str) -> Option<String> {
    std::fs::read_to_string(path).ok()
}

impl System {
    pub fn read(&self, disk: &std::path::Path) -> SystemStatus {
        let cpu = read("/proc/stat").and_then(|stat| {
            let line = stat.lines().next()?;
            let values: Vec<u64> =
                line.split_whitespace().skip(1).filter_map(|v| v.parse().ok()).collect();
            let idle = values.get(3)? + values.get(4).unwrap_or(&0);
            let total: u64 = values.iter().sum();
            let previous = self.0.lock().unwrap().replace((idle, total));
            let (last_idle, last_total) = previous?;
            let elapsed = total.checked_sub(last_total).filter(|t| *t > 0)?;
            Some(100.0 * (1.0 - (idle - last_idle) as f64 / elapsed as f64))
        });
        let memory = read("/proc/meminfo").and_then(|info| {
            let field = |name: &str| -> Option<f64> {
                info.lines().find(|l| l.starts_with(name))?.split_whitespace().nth(1)?.parse().ok()
            };
            Some(100.0 * (1.0 - field("MemAvailable:")? / field("MemTotal:")?))
        });
        let gpu = read(GPU_LOAD).and_then(|l| l.trim().parse::<f64>().ok()).map(|load| load / 10.0);
        let mut temperatures: Vec<Temperature> = std::fs::read_dir("/sys/class/thermal")
            .into_iter()
            .flatten()
            .filter_map(|entry| {
                let path = entry.ok()?.path();
                let name = read(path.join("type").to_str()?)?.trim().to_string();
                let millidegrees: f64 = read(path.join("temp").to_str()?)?.trim().parse().ok()?;
                // Unpopulated Jetson zones report -40 °C or less.
                (millidegrees > -40_000.0)
                    .then(|| Temperature { name, celsius: millidegrees / 1000.0 })
            })
            .collect();
        temperatures.sort_by(|a, b| a.name.cmp(&b.name));
        let uptime = read("/proc/uptime").and_then(|u| u.split_whitespace().next()?.parse().ok());
        SystemStatus {
            cpu_percent: cpu,
            memory_percent: memory,
            gpu_percent: gpu,
            disk_percent: disk_percent(disk),
            temperatures,
            uptime_s: uptime,
        }
    }
}

pub fn disk_percent(path: &std::path::Path) -> Option<f64> {
    let path = std::ffi::CString::new(path.as_os_str().as_encoded_bytes()).ok()?;
    // SAFETY: `stat` is written by statvfs before it is read.
    let mut stat: libc::statvfs = unsafe { std::mem::zeroed() };
    (unsafe { libc::statvfs(path.as_ptr(), &mut stat) } == 0 && stat.f_blocks > 0)
        .then(|| 100.0 * (1.0 - stat.f_bavail as f64 / stat.f_blocks as f64))
}
