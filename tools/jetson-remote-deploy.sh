#!/usr/bin/env bash
set -euo pipefail

case "${1:-test}" in
  test | switch) action=${1:-test} ;;
  --help | -h)
    cat <<'HELP'
Usage: bash tools/jetson-remote-deploy.sh [test|switch]

Builds Spot's NixOS system on the Jetson, downloading through this machine
over SSH, so the Jetson needs no Internet. Copies tracked working-tree files;
add new files to Git first.

test     Activate until the next reboot (default).
switch   Activate and make it the boot default.

SPOT_HOST    Jetson address (default: 192.168.69.170)
SPOT_CONFIG  Configuration to build (default: spot; spot-test for the test unit)
HELP
    exit 0
    ;;
  *) echo "Unexpected argument: $1. Use --help." >&2; exit 2 ;;
esac
config=${SPOT_CONFIG:-spot}

source_dir=$(cd "$(dirname "$0")/.." && pwd)
stage=$(mktemp -d /tmp/spot-deploy.XXXXXX)
control=$stage/ssh
ssh_jetson() { bash "$source_dir/tools/jetson-ssh.sh" -S "$control" "$@"; }
trap 'ssh_jetson -O exit >/dev/null 2>&1 || true; rm -rf -- "$stage"' EXIT

# One connection for the whole deploy; the Jetson downloads through its SOCKS forward.
bash "$source_dir/tools/jetson-ssh.sh" -M -S "$control" -fN \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -R 127.0.0.1:11080

# The Jetson has no clock source offline, and TLS needs a correct date.
git -C "$source_dir" ls-files -z |
  COPYFILE_DISABLE=1 tar --no-xattrs -C "$source_dir" -czf - --null -T - |
  ssh_jetson "sudo date -u -s @$(date +%s) >/dev/null && rm -rf ~/spot-src && mkdir ~/spot-src && tar -xzf - -C ~/spot-src"

ssh_jetson "cd ~/spot-src && sudo env NIX_REMOTE=local ALL_PROXY=socks5h://127.0.0.1:11080 \
  nix build path:.#nixosConfigurations.$config.config.system.build.toplevel --out-link /root/spot-next"

if [ "$action" = test ]; then
  ssh_jetson 'sudo /root/spot-next/bin/switch-to-configuration test'
else
  # shellcheck disable=SC2016 # Expands on the Jetson.
  ssh_jetson 'P=$(sudo readlink -f /root/spot-next) && sudo nix-env -p /nix/var/nix/profiles/system --set "$P" && sudo "$P/bin/switch-to-configuration" switch'
fi
