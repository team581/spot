# Seeed reComputer Robotics J401

This module targets the **Robotics J401_V1.0 carrier with an Orin Nano 8GB
(P3767-0003)**. It is not a definition for the Classic, Industrial, Mini, or
other Seeed carriers also called J401.

The connected unit runs Seeed's image
`mfi_recomputer-robo-orin-nano-8g-j401-gmsl-7.2.0-39.2.0-2026-06-22`,
with kernel `6.8.12-1021-tegra` and UEFI firmware `39.2.0-gcid-45755727`.
Its bootloader slots A and B report normal status. NixOS targets the pinned
JetPack 7.2.1 / L4T 39.2.1 stack. Its installer has booted on this carrier
using the copy-to-RAM option; full hardware qualification remains incomplete.

## Firmware and device tree

Seeed's firmware already supplies the carrier-specific device tree, pinmux,
and runtime fixups. The factory extlinux configuration has no `FDT` override,
and the running tree identifies the Seeed Robotics board. The NixOS module
keeps `hardware.deviceTree.name = null`, so systemd-boot also uses that
firmware-provided tree. Replacing it is outside this module's scope.

The firmware and board sources are published in
[Seeed's Robotics J401 BSP](https://github.com/Seeed-Studio/Linux_for_Tegra/tree/c018d61c5feb7951a16317b03ec9e0be6d6cb8cb/source/hardware/nvidia/t23x/nv-public).

Automatic capsule updates are disabled. The board target is unset and firmware
builds fail explicitly, so this flake cannot generate an NVIDIA developer-kit
flash image for the J401. The inherited `ota-check-firmware` diagnostic expects
the factory Seeed firmware identifier rather than a generated Nix firmware hash.
Use [Seeed's Robotics J401 BSP and procedure](https://wiki.seeedstudio.com/recomputer_robotics_j401_getting_started/)
for any deliberate firmware provisioning. NixOS generations do not roll back
QSPI firmware.

## Hardware configuration

- The maintenance port at PCI path `platform-140a0000.pcie-pci-0008:01:00.0`
  (`enP8p1s0` on Ubuntu) becomes `spot0`.
- The second port at `platform-141e0000.pcie-pci-0007:01:00.0`
  (`enP7p1s0`) becomes `spot1`.
- `spot0` uses Realtek `r8168`; `spot1` uses Microchip `lan743x`. The rules
  match physical paths rather than per-unit MAC addresses.
- The onboard USB hub driver loads in the initrd. Loading it after mounting
  a USB root disconnects the installer drive and causes filesystem I/O errors.
- Fan control uses NVIDIA's `nvfancontrol_p3767_0000.conf`, matching the factory
  symlink. Power management uses `nvpmodel_p3767_0003_super.conf`.
- The pinned NVIDIA kernel defconfig already enables the PCA953x GPIO expander,
  PCA954x I2C mux, PWM fan, NVMe, Tegra USB, and MCP251xFD CAN drivers.

The installed system and `.#installer` import the same board module and
maintenance access module. The installer authorizes the shared `team581` SSH
key and supplies `192.168.69.170/24` on `spot0`, without a default route.
It does not install the Spot application or automatically partition disks.

## Qualification

Validated on 2026-11-04: all-system flake evaluation and a complete native ARM64
Linux installer build passed. The ISO contains an ARM64 EFI loader, the expected
maintenance SSH key and separate NIC naming rules, and no automatic firmware
update service. Its fan configuration has the same SHA-256 as the factory file.
The installer USB was written and verified against the ISO by readback.

The first live boot reached NixOS 26.05 with the firmware-provided Seeed tree,
`spot0` at `192.168.69.170`, shared-key SSH, passwordless maintenance sudo, both
NIC names, visible NVMe, and successful 25W power-profile setup. No failed
system services were reported. The internal NVMe filesystems were not mounted.

Normal USB boot initially failed when the late-loading `onboard_usb_hub` driver
re-enumerated the hub and disconnected the live filesystem. Reloading the driver
in the RAM session reproduced the disconnect. Copying the ISO to RAM allowed
startup to finish. The module now loads that driver in the initrd; the rebuilt
installer still needs a normal USB boot test.

The physical cooler fan was found unplugged, with its lead unable to reach the
5V fan header. Zero RPM is therefore not evidence of a fan-driver failure. Resolve
the cable routing or extension with power disconnected, then verify fan speed
and temperatures before load testing. Keep the REC switch OFF for normal boot;
ON exposes NVIDIA APX recovery mode instead of starting an OS.

The live session also logged thermal-trip mailbox timeouts; their cause remains
unresolved and needs checking with working cooling. Testing stopped and shutdown
was requested. The corrected PNY installer passed readback verification on the
Jetson and is selected for the next boot only; Ubuntu remains the saved default.

Next verify normal USB boot, both Ethernet links and recovery, fan control, and
temperatures. Then install the full Spot system on spare storage and qualify
CUDA, all four UVC cameras, cold boot, offline operation, and generation recovery.

CAN, GMSL cameras, cellular, and other expansion interfaces are not claimed as
qualified by this module. The Spot application has not been deployed to this unit.
