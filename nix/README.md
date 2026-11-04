# Spot NixOS appliance

The target is a **Jetson Orin Nano 8GB on NVIDIA's developer-kit carrier board**,
using JetPack 6 and CUDA 12.6. Physically confirm the carrier before flashing.
Firmware changes are separate from normal deployments.

`flake.lock` pins Nixpkgs, `anduril/jetpack-nixos`, and Python build tooling.
`uv2nix` consumes the existing `uv.lock`, without a second Python dependency
list. Nix builds the CUDA extension, dashboard, and offline docs. Its store
replaces the old release directories, installer, mutable service files, and
activation symlink.

## Configuration

- `hosts/spot/configuration.nix`: board, disks, networking, access, and Spot.
- `module.nix`: services, socket, discovery, firewall, settings, and permissions.
- `packages.nix`: locked Python environment, native CUDA build, and web assets.

The built-in Realtek Ethernet adapter is named `spot0` by a udev link rule.
A low-priority NetworkManager profile supplies `192.168.69.170/24`, without a
default route. Confirmed GUI changes create higher-priority profiles and survive
reboot. Avahi advertises `spot.local` on `spot0` only. Confirm the NIC driver and
interface name during qualification.

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

1. Confirm the board and firmware. On Linux, build the pinned installer with
   `nix build path:.#installer`. Follow the
   [jetpack-nixos installation instructions](https://github.com/anduril/jetpack-nixos#readme)
   for its JetPack 6 installer. Build the installer on Linux. NVIDIA's firmware
   flashing tools need **x86_64 Linux**; the Mac cannot run them natively. Match
   JetPack 6 firmware to this configuration. OS rollback does not undo firmware.
2. Boot the installer. Prepare/mount a UEFI installation with an ext4 root
   labeled `SPOT_ROOT` at `/mnt` and a FAT EFI partition labeled `SPOT_EFI` at
   `/mnt/boot`. Adjust `fileSystems` for the actual storage layout if necessary.
   Preserve existing firmware partitions. No repository script formats disks.
3. Copy the checkout onto the installer and run from its root:

   ```sh
   sudo nixos-install --root /mnt --flake .#spot --no-root-passwd
   ```

4. Reboot and verify `spot0`, SSH, services, CUDA, USB discovery, and dashboard.
   Restore compatible state under `/var/lib/spot-vision`, owned by
   `spot-vision:spot-vision`, with Spot stopped. Complete hardware qualification.

The initial source build needs network access unless all build dependencies are
already available. The installed appliance needs no downloads to boot or run.
Budget 8GB of RAM and 20GB of free disk space for an initial source build; CUDA
compilation is limited to two parallel jobs for the Orin's memory budget.

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
