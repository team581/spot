# Project agent notes

## Jetson access

- Connect to the Spot Jetson with `ssh team581@192.168.69.170`.
- For a direct Ethernet connection from the development Mac, temporarily assign
  `192.168.69.171/24` to the connected Ethernet adapter when that subnet is not
  already configured.
- The Spot checkout on the Jetson is `/home/team581/spot-2026`.
- For NixOS installations, use `bash tools/jetson-ssh.sh` or `nix run path:.#ssh`.
  The repository intentionally includes a shared maintenance key authorized by
  `nix/hosts/spot/configuration.nix`; the helper gives its temporary copy the
  permissions required by OpenSSH.
- The connected hardware is an Orin Nano 8GB on a Seeed reComputer Robotics
  J401_V1.0 carrier, running Seeed JetPack 7.2 / L4T 39.2.0 on Ubuntu 24.04.
  Initial setup is complete and the shared maintenance SSH key is authorized.
  The connected Ethernet port is `enP8p1s0`; the other port is `enP7p1s0`.
  The NixOS host and installer use `nix/hardware/j401`, preserving Seeed's
  firmware-provided device tree. No NixOS hardware boot has been qualified yet.
  Never flash developer-kit firmware to this carrier. Firmware changes remain
  separate from normal NixOS deployments; see `nix/hardware/j401/README.md`.
- Never store the Jetson password in this repository. Request interactive SSH
  authentication only when the dedicated key is unavailable or has not yet
  been authorized.
