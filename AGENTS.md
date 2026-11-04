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
- The NixOS host is an Orin Nano 8GB on the NVIDIA developer-kit carrier board.
  Confirm the carrier board before flashing. Firmware changes are separate
  from normal NixOS deployments.
- Never store the Jetson password in this repository. Request interactive SSH
  authentication only when the dedicated key is unavailable or has not yet
  been authorized.
