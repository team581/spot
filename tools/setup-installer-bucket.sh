#!/usr/bin/env bash
set -euo pipefail

source_dir=$(cd "$(dirname "$0")/.." && pwd)
export CLOUDFLARE_ACCOUNT_ID=8bb70056a503857d02b48fc5db648f61

cf r2 buckets create --name spot-jetson-images
cf r2 buckets lifecycle update spot-jetson-images \
  --body "@$source_dir/.github/installer-r2-lifecycle.json"

cf r2 buckets domains custom create spot-jetson-images \
  --body "@$source_dir/.github/installer-r2-domain.json"
