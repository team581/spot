#!/usr/bin/env bash
set -euo pipefail

# Works with the laptop's SSH client; no Nix installation or network download.
source_dir=$(cd "$(dirname "$0")/.." && pwd)
key=$(mktemp)
trap 'rm -f "$key"' EXIT
install -m 0600 "$source_dir/nix/maintenance_ed25519" "$key"
ssh -i "$key" -o IdentitiesOnly=yes "team581@${SPOT_HOST:-10.99.91.11}" "$@"
