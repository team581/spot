# Project agent notes

## Jetson access

- Connect to the Spot Jetson with `ssh team581@192.168.69.170`.
- For a direct Ethernet connection from the development Mac, temporarily assign
  `192.168.69.171/24` to the connected Ethernet adapter when that subnet is not
  already configured.
- The Spot checkout on the Jetson is `/home/team581/spot-2026`.
- Use the dedicated SSH identity at `~/.ssh/spot_jetson_ed25519` for Jetson
  access. The corresponding public key must be present in the `team581`
  account's `~/.ssh/authorized_keys` file.
- Never store the Jetson password in this repository. Request interactive SSH
  authentication only when the dedicated key is unavailable or has not yet
  been authorized.
