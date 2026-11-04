# Spot NixOS appliance

The target is a **Jetson Orin Nano 8GB on a Seeed reComputer Robotics
J401_V1.0 carrier**, using JetPack 7.2.1 (L4T 39.2.1) and CUDA 13.2.
The J401 module is shared by the installed system and the installer.

The board must already have Seeed's Robotics J401 firmware. The current unit
runs firmware `39.2.0-gcid-45755727`, provisioned by Seeed's JetPack 7.2 image.
NixOS preserves its UEFI-provided device tree and board-specific pinmux rather
than installing a developer-kit DTB. Automatic firmware updates are disabled;
firmware-flashing outputs deliberately fail instead of producing developer-kit
firmware. See [J401 support and qualification](hardware/j401/README.md) for details.

Initial Ubuntu setup is complete and the maintenance SSH key is authorized on
the current unit. The NixOS installer has booted with copy-to-RAM and maintenance
SSH works. Normal USB boot after the hub-driver fix and hardware qualification
remain outstanding; the physical cooler fan needs connecting.

`flake.lock` pins Nixpkgs, `anduril/jetpack-nixos`, and Python build tooling.
`uv2nix` consumes the existing `uv.lock`, without a second Python dependency
list. Nix builds the CUDA extension, dashboard, and offline docs. Its store
replaces the old release directories, installer, mutable service files, and
activation symlink.

CI refreshes the pnpm dependency cache hash before Nix builds. The existing
autofix.ci workflow commits hash updates back to dependency branches, including
Renovate branches. No manual hash update is needed after changing dependencies.
To refresh it locally with Determinate Nix, run `bash tools/update-pnpm-deps-hash.sh`.

## Configuration

- `hardware/j401/default.nix`: carrier, firmware policy, power/fan control, and NIC names.
- `hosts/spot/maintenance.nix`: networking and SSH access shared with the installer.
- `hosts/spot/configuration.nix`: disks and the Spot application.
- `module.nix`: services, socket, discovery, firewall, settings, and permissions.
- `packages.nix`: locked Python environment, native CUDA build, and web assets.

The Ethernet adapters are named `spot0` and `spot1` by PCI-path udev link rules.
The Realtek port called `enP8p1s0` in Ubuntu becomes `spot0`; the Microchip port
`enP7p1s0` becomes `spot1`. These names were verified in the live installer.
Both adapters join the `br0` Ethernet bridge, so either socket can connect to the
robot network or a laptop. Nix supplies the fixed maintenance address
`192.168.69.170/24` on the bridge, without a default route. Avahi advertises
`spot.local` through the bridge. The ports share one Ethernet network; they are
not isolated links. Spanning Tree Protocol is enabled for redundant cabling.

The default profile supplies maintenance access only. For initial setup, put the
computer on `192.168.69.0/24`, connect through either port, and use
**Network → Jetson address** to choose the robot static IP or DHCP. Every trial
retains the maintenance address and automatically rolls back after 90 seconds
unless confirmed. Trials are memory-only. Confirmation saves one override at a
fixed priority and removes the previous override; the Nix profile and both member
profiles remain unchanged. The saved override survives reboot and Nix deployments.
`/etc/spot-vision/network.json` supplies the helper's bridge name, maintenance
address, and default profile UUID from the same Nix definitions.

Before making this topology the boot default, use a test deployment to qualify
both sockets individually, static and DHCP settings, timeout/revert recovery,
and persistence across reboot and a Nix generation change. Existing installer
evidence predates the bridge.

Spot runs as `spot-vision` with video/render access and a read-only system. The
privileged Ethernet helper is a separate service using a group-restricted Unix
socket. `/etc/spot-vision/installation.json` is generated from the module's
`services.spot-vision.settings` option using `pkgs.formats.json`. Calibration, assignments, cached profiles, and diagnostics
stay in `/var/lib/spot-vision`; generation changes do not erase them.

The service starts with `spot-vision run --installation
/etc/spot-vision/installation.json`. Custom launchers must use this command and
settings path; NixOS generates both together on the next deployment.

## First installation

This is an OS installation, not an in-place Ubuntu upgrade. Export the current
Spot configuration and copy `/var/lib/spot-vision` and historical calibration
files elsewhere before changing storage. Use spare storage for the first trial
so the Ubuntu installation remains available.

1. Confirm the Robotics J401 carrier and the existing Seeed firmware. On Linux,
   build the board-specific installer with `nix build path:.#installer`. An ARM
   Linux VM/container on a development Mac can perform this build. This installer
   includes the same J401 module, `team581` SSH key, and maintenance network as
   the installed system. It does not flash firmware. If firmware provisioning is
   needed, follow [Seeed's Robotics J401 instructions](https://wiki.seeedstudio.com/recomputer_robotics_j401_getting_started/)
   separately; NVIDIA recovery flashing requires an x86_64 Linux host.
2. Boot the installer from removable storage using the UEFI boot menu. Verify
   SSH, both Ethernet ports, NVMe, USB, fan control, and temperatures before
   changing the internal SSD. For installation on spare storage, prepare/mount
   an ext4 root labeled `SPOT_ROOT` at `/mnt` and a FAT EFI partition labeled
   `SPOT_EFI` at `/mnt/boot`. Adjust `fileSystems` for the actual layout.
   Preserve the existing firmware partitions. No repository script formats disks.
3. Copy the checkout onto the installer and run from its root:

   ```sh
   sudo nixos-install --root /mnt --flake .#spot --no-root-passwd
   ```

4. Reboot and verify `spot0`, SSH, services, CUDA, USB discovery, and dashboard.
   Restore compatible state under `/var/lib/spot-vision`, owned by
   `spot-vision:spot-vision`, with Spot stopped. Complete hardware qualification.

The initial source build needs network access unless all build dependencies are
already available. The installed appliance needs no downloads to boot or run.
Allow at least 60GB of free disk space for the first kernel/installer source
build, including downloads, unpacked sources, and temporary build files. CUDA
compilation is limited to two parallel jobs for the Orin's memory budget.

For a Docker builder on an Apple Silicon Mac, explicitly allocate resources at
container creation, for example `--platform linux/arm64 --memory 16g --cpus 8`,
and build with `--max-jobs 1 --cores 8`. Apple Container defaults to a 1GB VM and
cannot change its resources in place. Monitor the Mac's free disk space as well
as the guest: the guest reports its virtual disk capacity, not the remaining
space on the Mac. A Linux container builder keeps Nix off the factory Ubuntu
installation.

The Linux builder also needs a case-sensitive Nix store. NVIDIA's multimedia
archive contains both `NvBufSurface.h` and `nvbufsurface.h`. With a
case-insensitive macOS `/nix` volume, Determinate's built-in Linux builder fails
copying these headers with `File exists`. Build entirely inside a Linux
container with its own `/nix`, rather than sharing the Mac's store. For the
existing `spot-j401-builder` container on this Mac:

```sh
docker start spot-j401-builder
docker exec -w /workspace spot-j401-builder \
  nix --extra-experimental-features 'nix-command flakes' \
  build path:.#packages.aarch64-linux.installer -L \
  --max-jobs 1 --cores 8 --out-link /tmp/spot-installer
```

On this Mac's Docker compatibility layer, copying the ISO with `docker cp` via
its result symlink produced an empty file. Streaming the resolved ISO with
`docker exec ... cat` worked; compare its SHA-256 with the container's original
before writing installation media.

## SSH at an event

The repository intentionally includes the team's shared maintenance private and
public key. `team581` is authorized with the public key and has passwordless sudo.
No separate credential distribution is required. From any checkout, even without
Nix or internet access:

```sh
bash tools/jetson-ssh.sh
bash tools/jetson-ssh.sh sudo systemctl status spot-vision
```

The helper copies the key to a temporary file with mode `0600`, uses it for SSH,
then removes the copy. This works after a Git checkout with mode `0644` too.
`nix run path:.#ssh` provides the equivalent packaged command.

Set `SPOT_HOST` to use a different IP address or hostname with either SSH helper
or the deployment command:

```sh
export SPOT_HOST=spot.local
bash tools/jetson-ssh.sh
nix run .#deploy -- test
```

The default is `192.168.69.170`. IPv6 link-local addresses must include the local
interface scope, for example `SPOT_HOST=fe80::1234%en7` on a Mac.

For a direct cable, configure the Mac Ethernet adapter as `192.168.69.171/24`.
Open `http://192.168.69.170:5800/` or `http://spot.local:5800/` for the dashboard.

## Build, test, and deploy

From the repository root on a development Mac or Linux machine:

```sh
nix flake check path:. --all-systems --no-build
# Build on Spot and activate temporarily; the boot default stays unchanged.
nix run .#deploy -- test
# With a disabled robot, check the package, profile, clock, and cameras.
bash tools/jetson-ssh.sh spot-vision check-health --robot
# Persist the same configuration after verification.
nix run .#deploy -- switch
```

Do not edit the checkout between `test` and `switch`. Spot uses systemd's notify
protocol to signal startup after the native module, saved state, and web server
have initialized. `spot-vision check-health` checks HTTP availability and the
running Nix package path. Add `--robot` to require a disabled robot, acknowledged
profile, synchronized clock, and fresh calibrated camera detections. Booting
without a roboRIO still allows maintenance access.

Git-backed flake commands include tracked files and expose the configuration
revision through NixOS's `system.configurationRevision`. Add new files to Git
before deploying. Use `path:.` for evaluating an untracked development snapshot;
that snapshot has no Git revision. Package identity comes from the Nix store
path; no application manifest, source-tree hashing, or release ID is generated.
Nix's `nix store verify` provides store integrity diagnostics when needed.

Installation settings are ordinary NixOS configuration, for example:

```nix
services.spot-vision.settings = {
  nt.team = 581;
  http.port = 5800;
  processing.max_fps = 30;
};
```

Deployment uses the shared key and `nixos-rebuild`, with Spot as both build host
and target. Spot must already run NixOS. ARM CUDA compilation runs on Linux;
macOS evaluation is not evidence of a working GPU build. CPU packages are also
available on macOS ARM and Linux x86 via `nix build path:.#spot-vision`.

This uses standard NixOS generations, **without automatic remote rollback**.
A failed `test` can leave services on the attempted generation. Restore the
persistent boot configuration after a failed test:

```sh
bash tools/jetson-ssh.sh sudo /nix/var/nix/profiles/system/bin/switch-to-configuration test
```

After a persisted switch, restore the previous generation:

```sh
bash tools/jetson-ssh.sh sudo nixos-rebuild switch --rollback
```

If networking is unavailable, use the boot menu to select an older retained
generation. Rollback restores system/application configuration, not calibration
state or firmware. Keep configuration exports when changing state.

## Offline deployment

Build and retain the complete ARM system closure before competition. On an ARM
Linux builder configured for this flake, export an archive for transfer:

```sh
nix build .#nixosConfigurations.spot.config.system.build.toplevel
readlink -f result > spot-system-path
nix-store --export $(nix-store -qR result) > spot-system.nar
```

Copy both files to Spot over Ethernet or removable storage. On Spot:

```sh
sudo nix-store --import < spot-system.nar
system=$(cat spot-system-path)
sudo "$system/bin/switch-to-configuration" test
spot-vision check-health --robot
# Persist after the test succeeds.
sudo nix-env --profile /nix/var/nix/profiles/system --set "$system"
sudo "$system/bin/switch-to-configuration" switch
```

The archive contains transitive runtime dependencies, so activation does not
fetch packages. Retain the previous generation for recovery at an event.

## Hardware qualification

Verify cold boot, power/fan control, CUDA imports and detections, all four UVC
cameras, permissions, capture timing, roboRIO synchronization, network checkpoint
recovery, offline docs, and previous-generation recovery. Record the system
system/package store paths and configuration revision from `/health`. Software evaluation
and CPU smoke tests do not establish Jetson hardware qualification.
