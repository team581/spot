---
title: Jetson installation and recovery
---

This flake targets an Orin Nano on the **Seeed reComputer Robotics J401** carrier.
Never flash NVIDIA developer-kit firmware onto it. Firmware provisioning is
separate from NixOS deployment; the [board module](https://github.com/team581/spot-2026/blob/main/nix/hardware/j401/default.nix)
preserves the firmware-provided device tree and disables automatic firmware updates.

## Connect

For direct Ethernet, give the laptop `192.168.69.171/24`, then:

```sh
bash tools/jetson-ssh.sh
```

The helper uses the repository's shared maintenance key for `team581` with
passwordless sudo. Set `SPOT_HOST` to override `192.168.69.170`.
The [maintenance config](https://github.com/team581/spot-2026/blob/main/nix/hosts/spot/maintenance.nix) bridges both Ethernet ports;
they are on the same network.

## First installation

Build `nix build path:.#installer` on ARM Linux with a case-sensitive Nix store.
Before installing, back up existing storage and verify hardware operation and the
partition layout in [the host config](https://github.com/team581/spot-2026/blob/main/nix/hosts/spot/configuration.nix). Use spare
storage for trials. With the target root and EFI partitions mounted at `/mnt`
and `/mnt/boot`, run from a copy of this repository on the installer:

```sh
sudo nixos-install --root /mnt --flake .#spot --no-root-passwd
```

## Deploy to an existing NixOS installation

Run from the development checkout; no checkout on the Jetson is needed:

```sh
nix run .#deploy -- test
bash tools/jetson-ssh.sh spot-vision check-health --robot
nix run .#deploy -- switch
```

Add new files to Git before deploying and keep the checkout unchanged between
`test` and `switch`. `test` changes the running system but leaves the boot default
unchanged. There is no automatic deployment rollback. `check-health --robot`
checks runtime readiness with a disabled robot; it does not certify hardware accuracy.

## Recover

Restore the saved boot configuration after a failed test:

```sh
bash tools/jetson-ssh.sh sudo /nix/var/nix/profiles/system/bin/switch-to-configuration test
```

Undo a persisted switch:

```sh
bash tools/jetson-ssh.sh sudo nixos-rebuild switch --rollback
```

If SSH is unavailable, select an older retained generation in the boot menu.
Rollback does not restore firmware or application state in `/var/lib/spot-vision`;
back up that directory before state changes. Inspect service logs with
`bash tools/jetson-ssh.sh sudo journalctl -u spot-vision -b`.
