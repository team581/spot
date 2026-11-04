#!/usr/bin/env bash
set -euo pipefail

started_at=$(date +%s)
if ! nix build path:.#web.pnpmDeps --no-link; then
  determinate-nixd fix hashes --auto-apply --since "$started_at" nix
  nix build path:.#web.pnpmDeps --no-link
fi
