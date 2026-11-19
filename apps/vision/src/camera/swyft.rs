//! Rewrites a SWYFT camera's USB serial in its SPI flash. The camera's Realtek bridge exposes flash
//! and register access through UVC extension unit 4: selector 10 takes an 8-byte command, and
//! selector 11 carries its data 8 bytes at a time. Only the 256-byte USB config block at `0xAE00`
//! changes; it sits alone in its 4 KiB sector, so the firmware code is never erased.
#![cfg_attr(not(target_os = "linux"), allow(dead_code))]

/// USB vendor and product IDs of the SWYFT camera's bridge.
pub const USB_ID: (&str, &str) = ("0bda", "3035");

const BLOCK: usize = 0x100;
const SERIAL: u8 = 3;

/// Whether `serial` can be written: the vendor allows only ASCII letters and digits, at most 48.
pub fn valid_serial(serial: &str) -> bool {
    (1..=48).contains(&serial.len()) && serial.bytes().all(|b| b.is_ascii_alphanumeric())
}

/// Replaces or adds the serial record in a config block. The block is a `55 a5` magic, a flag
/// byte, the used length, a big-endian record count, then records of `[length, type, data…]`.
/// The serial record (type 3) holds an ASCII USB string descriptor.
fn with_serial(block: &[u8], serial: &str) -> Result<Vec<u8>, String> {
    if block.len() != BLOCK || block[..2] != [0x55, 0xa5] {
        return Err("the camera's USB config block is missing".into());
    }
    let (used, count) = (block[3] as usize, u16::from_be_bytes([block[4], block[5]]));
    let mut records = Vec::new();
    let mut at = 6;
    for _ in 0..count {
        let length = *block.get(at).ok_or("the camera's USB config block is malformed")? as usize;
        if length < 2 || at + length > used {
            return Err("the camera's USB config block is malformed".into());
        }
        records.push(&block[at..at + length]);
        at += length;
    }
    if at != used {
        return Err("the camera's USB config block is malformed".into());
    }
    let descriptor = [&[serial.len() as u8 + 2, 0x03], serial.as_bytes()].concat();
    let record = [&[descriptor.len() as u8 + 2, SERIAL], &descriptor[..]].concat();
    let records: Vec<&[u8]> =
        records.into_iter().filter(|r| r[1] != SERIAL).chain([&record[..]]).collect();
    let body = records.concat();
    let mut out = vec![0x55, 0xa5, block[2], (6 + body.len()) as u8];
    out.extend((records.len() as u16).to_be_bytes());
    out.extend(body);
    out.resize(BLOCK, 0xff);
    Ok(out)
}

#[cfg(target_os = "linux")]
pub use device::set_serial;

#[cfg(not(target_os = "linux"))]
pub fn set_serial(_path: &str, _serial: &str) -> anyhow::Result<()> {
    anyhow::bail!("setting a serial needs Linux")
}

#[cfg(target_os = "linux")]
mod device {
    use std::fs::File;
    use std::os::fd::AsRawFd;
    use std::time::{Duration, Instant};

    use anyhow::{Context, bail, ensure};

    use super::{BLOCK, valid_serial, with_serial};

    const SECTOR: u32 = 0xA000;
    const CONFIG: u32 = 0xAE00;
    /// Bit 0 of each releases the flash's write-protect pin.
    const WRITE_PROTECT: [u32; 2] = [0xFEA0, 0xFEA6];
    /// The controller and flash this was verified on. Other revisions may lay out flash differently.
    const CONTROLLER: [u8; 2] = [0x10, 0x60];
    const FLASH: [u8; 3] = [0x30, 0x5e, 0x11];

    #[repr(C)]
    struct XuQuery {
        unit: u8,
        selector: u8,
        query: u8,
        size: u16,
        data: *mut u8,
    }

    // _IOWR('u', 0x21, struct uvc_xu_control_query)
    const UVCIOC_CTRL_QUERY: u64 =
        (3 << 30) | ((size_of::<XuQuery>() as u64) << 16) | ((b'u' as u64) << 8) | 0x21;
    const SET_CUR: u8 = 0x01;
    const GET_CUR: u8 = 0x81;

    struct Bridge(File);

    impl Bridge {
        fn query(&self, selector: u8, query: u8, data: &mut [u8; 8]) -> anyhow::Result<()> {
            let mut request =
                XuQuery { unit: 4, selector, query, size: 8, data: data.as_mut_ptr() };
            // SAFETY: `request` points at an 8-byte buffer that outlives the call.
            let result =
                unsafe { libc::ioctl(self.0.as_raw_fd(), UVCIOC_CTRL_QUERY as _, &mut request) };
            ensure!(result == 0, std::io::Error::last_os_error());
            Ok(())
        }

        fn command(&self, kind: u8, opcode: u8, address: u32, length: usize) -> anyhow::Result<()> {
            let mut packet = [kind, opcode, 0, 0, 0, 0, 0, 0];
            packet[2..4].copy_from_slice(&(address as u16).to_le_bytes());
            packet[4..6].copy_from_slice(&(length as u16).to_le_bytes());
            packet[6..8].copy_from_slice(&((address >> 16) as u16).to_le_bytes());
            self.query(10, SET_CUR, &mut packet)
        }

        fn read(
            &self,
            kind: u8,
            opcode: u8,
            address: u32,
            length: usize,
        ) -> anyhow::Result<Vec<u8>> {
            self.command(kind, opcode, address, length)?;
            let mut out = Vec::with_capacity(length + 8);
            while out.len() < length {
                let mut chunk = [0; 8];
                self.query(11, GET_CUR, &mut chunk)?;
                out.extend(chunk);
            }
            out.truncate(length);
            Ok(out)
        }

        fn write(&self, kind: u8, opcode: u8, address: u32, data: &[u8]) -> anyhow::Result<()> {
            self.command(kind, opcode, address, data.len())?;
            for chunk in data.chunks(8) {
                let mut padded = [0; 8];
                padded[..chunk.len()].copy_from_slice(chunk);
                self.query(11, SET_CUR, &mut padded)?;
            }
            Ok(())
        }

        fn register(&self, address: u32) -> anyhow::Result<u8> {
            Ok(self.read(0, 0xC2, address, 1)?[0])
        }

        fn set_register(&self, address: u32, value: u8) -> anyhow::Result<()> {
            self.write(0, 0x82, address, &[value])?;
            let actual = self.register(address)?;
            ensure!(
                actual == value,
                "register {address:#06x} reads {actual:#04x}, not {value:#04x}"
            );
            Ok(())
        }

        fn status(&self) -> anyhow::Result<u8> {
            Ok(self.read(2, 0xC3, 0, 1)?[0])
        }

        /// Waits for the flash to finish an erase or write.
        fn wait(&self, what: &str) -> anyhow::Result<u8> {
            std::thread::sleep(Duration::from_millis(20));
            let deadline = Instant::now() + Duration::from_secs(3);
            loop {
                let status = self.status()?;
                if status & 1 == 0 {
                    return Ok(status);
                }
                ensure!(Instant::now() < deadline, "{what} timed out");
                std::thread::sleep(Duration::from_millis(10));
            }
        }

        fn set_status(&self, value: u8) -> anyhow::Result<u8> {
            self.write(2, 0x83, 0, &[value])?;
            self.wait("status register write")
        }

        fn flash(&self, address: u32, length: usize) -> anyhow::Result<Vec<u8>> {
            self.read(2, 0xC2, address, length)
        }
    }

    /// Rewrites the serial of the SWYFT camera at `path`. It takes effect when the camera is
    /// replugged. The caller must make sure nothing is streaming from the camera.
    pub fn set_serial(path: &str, serial: &str) -> anyhow::Result<()> {
        ensure!(valid_serial(serial), "a serial must be 1 to 48 letters and digits");
        let bridge = Bridge(File::options().read(true).write(true).open(path).context("open")?);
        let controller = bridge.read(0, 0xC2, 0xFE21, 2).context("read controller")?;
        // The firmware rejects this read unless it asks for all 8 bytes.
        let flash = bridge.read(2, 0xC1, 0, 8).context("read flash ID")?;
        ensure!(
            controller == CONTROLLER && flash[..3] == FLASH,
            "unsupported camera revision (controller {controller:02x?}, flash {flash:02x?})"
        );
        let status = bridge.status()?;
        let pins = [bridge.register(WRITE_PROTECT[0])?, bridge.register(WRITE_PROTECT[1])?];
        ensure!(
            status & 0xFC == 0x8C && pins.iter().all(|p| p & 1 == 0),
            "flash protection is in an unexpected state (status {status:#04x})"
        );

        let sector = bridge.flash(SECTOR, 0x1000).context("read flash")?;
        let offset = (CONFIG - SECTOR) as usize;
        let outside = sector[..offset].iter().chain(&sector[offset + BLOCK..]);
        ensure!(outside.into_iter().all(|&b| b == 0xff), "the config sector holds other data");
        let old = &sector[offset..offset + BLOCK];
        let new = with_serial(old, serial).map_err(anyhow::Error::msg)?;
        if new == old {
            return Ok(());
        }

        let written = (|| {
            for (address, pin) in WRITE_PROTECT.into_iter().zip(pins) {
                bridge.set_register(address, pin | 1)?;
            }
            let unlocked = bridge.set_status(0)?;
            ensure!(unlocked & 0x9C == 0, "flash protection did not clear");
            bridge.command(2, 0x05, SECTOR, 0)?;
            bridge.wait("erase")?;
            ensure!(bridge.flash(SECTOR, 0x1000)?.iter().all(|&b| b == 0xff), "erase failed");
            bridge.write(2, 0x82, CONFIG, &new)?;
            bridge.wait("write")?;
            ensure!(bridge.flash(CONFIG, BLOCK)? == new, "the written config doesn't verify");
            Ok(())
        })();
        let restored = (|| {
            let restored = bridge.set_status(status & 0xFC)?;
            for (address, pin) in WRITE_PROTECT.into_iter().zip(pins).rev() {
                bridge.set_register(address, pin)?;
            }
            ensure!(restored & 0xFC == status & 0xFC, "flash protection was not restored");
            Ok(())
        })();
        if let Err(error) = restored {
            let written = written.err().map_or("succeeded".into(), |e| format!("failed: {e:#}"));
            bail!("restoring flash protection failed: {error:#}; the write {written}");
        }
        written.context("writing the serial failed")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block(hex: &str) -> Vec<u8> {
        let mut bytes: Vec<u8> =
            hex.split_whitespace().map(|b| u8::from_str_radix(b, 16).unwrap()).collect();
        bytes.resize(BLOCK, 0xff);
        bytes
    }

    #[test]
    fn adds_a_serial_record() {
        // A camera as shipped, and the block that made it enumerate as FRONT.
        let shipped = block("55 a5 92 0f 00 02 06 2f 42 58 60 10 03 08 d2");
        let front =
            block("55 a5 92 18 00 03 06 2f 42 58 60 10 03 08 d2 09 03 07 03 46 52 4f 4e 54");
        assert_eq!(with_serial(&shipped, "FRONT").unwrap(), front);
        assert_eq!(with_serial(&front, "FRONT").unwrap(), front);
    }

    #[test]
    fn replaces_an_existing_serial_and_keeps_other_records() {
        // SWYFT's stock firmware image, with manufacturer, product, and placeholder serial records.
        const RECORDS: &str = "06 2f 42 58 60 10 03 08 d2 \
            12 01 10 03 53 57 59 46 54 20 52 6f 62 6f 74 69 63 73 \
            1b 02 19 03 53 57 59 46 54 20 55 53 42 20 43 41 4d 45 52 41 20 4f 56 39 32 38 31";
        let stock = block(&format!(
            "55 a5 92 63 00 05 {RECORDS} 27 03 25 03 45 6e 74 65 72 55 6e 69 71 75 65 49 44 28 \
             45 47 3a 46 52 4f 4e 54 2f 42 41 43 4b 2f 49 4e 54 41 4b 45 29"
        ));
        let back = block(&format!("55 a5 92 44 00 05 {RECORDS} 08 03 06 03 42 41 43 4b"));
        assert_eq!(with_serial(&stock, "BACK").unwrap(), back);
    }

    #[test]
    fn rejects_a_malformed_block() {
        assert!(with_serial(&block("ff ff"), "A").is_err());
        assert!(with_serial(&block("55 a5 92 0f 00 03 06 2f 42 58 60 10 03 08 d2"), "A").is_err());
    }

    #[test]
    fn serials_are_letters_and_digits() {
        assert!(valid_serial("FRONT2"));
        assert!(!valid_serial(""));
        assert!(!valid_serial("front left"));
        assert!(!valid_serial(&"A".repeat(49)));
    }
}
