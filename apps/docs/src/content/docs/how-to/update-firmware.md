---
title: Update a Jetson's firmware
description: Flash Seeed's JetPack 7 firmware onto a J401 from an Apple Silicon Mac, then install Spot.
---

This guide flashes a J401 that came with JetPack 6 to the [firmware Spot needs](../../reference/jetson/#firmware), then installs Spot.
Flashing erases the NVMe drive.

:::danger
Only flash Seeed's image for the **reComputer Robotics J401** with an **Orin Nano 8GB**.
Never flash NVIDIA developer-kit firmware onto the J401.
:::

## Check the current firmware

```sh
mise run jetson:ssh -- cat /sys/class/dmi/id/bios_version
```

The serial console also shows the version on the firmware's setup screen, which opens when you press Esc during boot.
If the version is `39.2.0-gcid-45755727`, skip to [Set up a new Jetson](../set-up-jetson/).

## Before you start

You need:

- An Apple Silicon Mac with [Homebrew](https://brew.sh/) `qemu`, `sudo` rights, and 50 GiB free.
- A USB-C data cable from the Mac to the J401's [debug port](../../reference/jetson/#debug-port).
- To install Spot without a USB drive, a microSD card in the Jetson.

Copy `/var/lib/spot-vision` off the Jetson if you want to keep it.
Spot starts with empty state after reinstalling.

## Download the image

The [J401 getting started page](https://wiki.seeedstudio.com/recomputer_robotics_j401_getting_started/) links the image in its JetPack 7.2 row for the Orin Nano 8GB.
Download the 13.5 GB file and check it:

```sh
mkdir -p ~/Downloads/seeed-j401-jp7 && cd ~/Downloads/seeed-j401-jp7
url='https://seeedstudio88-my.sharepoint.com/:u:/g/personal/youjiang_yu_seeedstudio88_onmicrosoft_com/IQBxz11HG6naSak2wIytiRbXAaqxhsgIWFaVR9H9GfGWqus?download=1'
curl -fL -C - --retry 5 -c cookies -b cookies -o mfi_recomputer-robo-orin-nano-8g-j401-gmsl-7.2.0-39.2.0-2026-06-22.tar.gz "$url"
echo '23b68b43e630d166e5079f72509c71ea0e13f76e372ddd06fe22df5494ad3f41  mfi_recomputer-robo-orin-nano-8g-j401-gmsl-7.2.0-39.2.0-2026-06-22.tar.gz' | shasum -a 256 -c -
```

Seeed's page splits the SHA-256 across two lines.

## Create the flash VM

Use Homebrew's QEMU, not UTM.
UTM resets the device when it attaches it, and the boot ROM then refuses the flash until the next power cycle.

1. Create the VM's disk, SSH key, and cloud-init seed:

   ```sh
   mkdir -p ~/jetson-flash && cd ~/jetson-flash
   curl -fLO https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img
   curl -fLO https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
   grep ' \*noble-server-cloudimg-arm64.img$' SHA256SUMS | shasum -a 256 -c -
   cp noble-server-cloudimg-arm64.img disk.qcow2
   qemu-img resize disk.qcow2 100G
   ssh-keygen -q -t ed25519 -N '' -C jetson-flash -f id_ed25519
   dd if=/dev/zero of=vars.fd bs=1m count=64
   mkdir -p seed
   printf 'instance-id: jetson-flash-1\nlocal-hostname: jetson-flash\n' > seed/meta-data
   cat > seed/user-data <<EOF
   #cloud-config
   users:
     - name: flash
       sudo: ALL=(ALL) NOPASSWD:ALL
       shell: /bin/bash
       ssh_authorized_keys:
         - $(cat id_ed25519.pub)
   package_update: true
   packages: [qemu-user-static, binfmt-support, usbutils, nfs-kernel-server, pigz, abootimg, binutils, cpp, device-tree-compiler, dosfstools, lbzip2, libxml2-utils, openssl, python3-yaml, sshpass, udev, uuid-runtime, whois, rsync, zstd, lz4, xmlstarlet]
   runcmd:
     - [sh, -c, 'apt-get install -y linux-modules-extra-$(uname -r)']
   EOF
   hdiutil makehybrid -iso -joliet -default-volume-name cidata -o seed.iso seed
   ```

2. Write the launcher:

   ```sh
   cat > ~/jetson-flash/run-qemu.sh <<'EOF'
   #!/usr/bin/env bash
   cd "$(dirname "$0")"
   exec qemu-system-aarch64 -name jetson-flash -machine virt -accel hvf -cpu host -smp 6 -m 8192 \
     -drive if=pflash,format=raw,readonly=on,file=/opt/homebrew/share/qemu/edk2-aarch64-code.fd \
     -drive if=pflash,format=raw,file=vars.fd \
     -drive if=virtio,file=disk.qcow2 -drive if=virtio,format=raw,file=seed.iso \
     -netdev user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22 -device virtio-net-pci,netdev=n0 \
     -device usb-ehci,id=ehci \
     -device usb-host,id=rcm,bus=ehci.0,vendorid=0x0955,productid=0x7523,guest-reset=false \
     -device usb-host,id=initrd,bus=ehci.0,vendorid=0x0955,productid=0x7035,guest-reset=false \
     -display none -serial file:console.log -monitor unix:monitor.sock,server,nowait
   EOF
   chmod +x ~/jetson-flash/run-qemu.sh
   ```

   Keep `guest-reset=false`, for the same reason as avoiding UTM.
   Pass through only these two product IDs, the boot ROM and Seeed's flashing system.
   The Jetson's normal USB device, `0955:7020`, crashes QEMU.

3. Start the VM in its own terminal and leave it running:

   ```sh
   sudo ~/jetson-flash/run-qemu.sh 2>&1 | grep -v libusb_kernel_driver_active
   ```

4. In another terminal, define a shortcut for the VM, wait for its first boot to finish, and load the USB network drivers:

   ```sh
   vm() { ssh -i ~/jetson-flash/id_ed25519 -p 2222 -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR flash@127.0.0.1 "$@"; }
   vm 'cloud-init status --wait; sudo modprobe -a rndis_host cdc_ether cdc_ncm'
   ```

5. Unpack the image into the VM:

   ```sh
   vm 'sudo mkdir -p /flash && sudo tar -C /flash -I pigz -xpf -' < ~/Downloads/seeed-j401-jp7/mfi_recomputer-robo-orin-nano-8g-j401-gmsl-7.2.0-39.2.0-2026-06-22.tar.gz
   ```

To stop the VM, run `vm 'sudo systemctl poweroff'`.
To start it again, repeat step 3, then step 4's `modprobe`.

## Flash the firmware

1. Set the DIP switch to RESET/REC, then unplug the Jetson's power and plug it back in.
2. Check that the VM lists `0955:7523 NVIDIA Corp. APX`:

   ```sh
   vm 'lsusb | grep 0955'
   ```

3. Flash:

   ```sh
   vm 'sudo bash -c "cd /flash/mfi_recomputer-orin-robotics-j401-gmsl && setsid nohup ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs > /flash/flash.log 2>&1 < /dev/null &"'
   ```

4. Check the log until it ends with `Flashing success`, about 10 minutes later:

   ```sh
   vm 'grep -a -v "Waiting for target" /flash/flash.log | tail'
   ```

   The Jetson then boots Seeed's Ubuntu from the NVMe, which installing Spot replaces.

If the log stops at `ERROR: might be timeout in USB write.` after `Sending bct_br`, power-cycle the Jetson and repeat step 3.
The boot ROM accepts one attempt per power cycle.

## Install Spot

With a USB drive, set the DIP switch to debug and follow [Set up a new Jetson](../set-up-jetson/).

Without one, write the installer to the microSD card from Seeed's flashing system:

1. With the switch still on RESET/REC, power-cycle the Jetson.
2. Download and check the installer:

   ```sh
   vm 'cd /flash && sudo curl -fLO https://downloads.spot.frc581.com/latest/spot-installer.iso && sudo curl -fLO https://downloads.spot.frc581.com/latest/spot-installer.iso.sha256 && sha256sum -c spot-installer.iso.sha256'
   ```

3. Boot the flashing system without flashing:

   ```sh
   vm 'sudo bash -c "cd /flash/mfi_recomputer-orin-robotics-j401-gmsl && setsid nohup ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --initrd --showlogs > /flash/initrd.log 2>&1 < /dev/null &"'
   ```

   Wait until `/flash/initrd.log` says `Device has booted into initrd`.

4. Check that `mmcblk0` is the microSD card, of type `SD`:

   ```sh
   vm 'sudo sshpass -p root ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@fc00:1:1:0::2 "cat /proc/partitions; cat /sys/block/mmcblk0/device/type"'
   ```

5. Write the installer, then compare the written hash with the published one:

   ```sh
   vm 'cd /flash && sudo sshpass -p root ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@fc00:1:1:0::2 "dd of=/dev/mmcblk0 bs=4M conv=fsync" < spot-installer.iso'
   vm 'cd /flash && sudo sshpass -p root ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@fc00:1:1:0::2 "head -c $(stat -c %s spot-installer.iso) /dev/mmcblk0 | sha256sum"; cat spot-installer.iso.sha256'
   ```

6. Stop the VM with `vm 'sudo systemctl poweroff'`.
7. Set the DIP switch to debug, open the serial console, and power-cycle the Jetson.
8. Press Esc when the firmware offers it, choose **Boot Manager**, then the **SD Device** entry.
9. Continue from step 3 under [Install](../set-up-jetson/#install) in Set up a new Jetson.
10. Once Spot runs, erase the installer so it can't boot again:

    ```sh
    mise run jetson:ssh -- sudo wipefs -a /dev/mmcblk0
    ```
