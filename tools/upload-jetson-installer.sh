#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_ACCOUNT_ID:?}"
: "${R2_BUCKET:?}"
: "${GITHUB_SHA:?}"
: "${GITHUB_RUN_ID:?}"
: "${GITHUB_STEP_SUMMARY:?}"

endpoint="https://$CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com"
destination="s3://$R2_BUCKET/latest"
mkdir -p dist/installer
ln -sf "$(realpath result/iso/*.iso)" dist/installer/spot-installer.iso
cd dist/installer
sha256sum spot-installer.iso > spot-installer.iso.sha256

# Replacing fixed keys retains only the latest uploaded build.
aws s3 cp spot-installer.iso "$destination/spot-installer.iso" \
  --endpoint-url "$endpoint" --only-show-errors \
  --metadata "commit=$GITHUB_SHA,run-id=$GITHUB_RUN_ID"
aws s3 cp spot-installer.iso.sha256 "$destination/spot-installer.iso.sha256" \
  --endpoint-url "$endpoint" --only-show-errors --content-type text/plain

iso_url=$(aws s3 presign "$destination/spot-installer.iso" --endpoint-url "$endpoint" --expires-in 604800)
checksum_url=$(aws s3 presign "$destination/spot-installer.iso.sha256" --endpoint-url "$endpoint" --expires-in 604800)
# Job summaries redact the access-key ID embedded in signed URLs. Keep working
# links in a small private artifact instead; the ISO itself stays in R2.
{
  printf '<!doctype html><html lang="en"><meta charset="utf-8"><title>Spot installer</title>\n'
  printf '<h1>Spot offline installer</h1><p>Commit: %s</p>\n' "$GITHUB_SHA"
  printf '<p><a href="%s">Download installer</a></p>\n' "$iso_url"
  printf '<p><a href="%s">Download SHA-256 checksum</a></p>\n' "$checksum_url"
  printf '<p>Links expire after seven days and always refer to the latest uploaded build.</p>\n'
  printf '<p>Download both files together and verify with <code>shasum -a 256 -c spot-installer.iso.sha256</code>.</p></html>\n'
} > downloads.html
{
  printf 'Built commit %s. ISO size: %s bytes.\n\n' "$GITHUB_SHA" "$(stat -Lc %s spot-installer.iso)"
  printf 'Download the installer-downloads artifact and open downloads.html for private R2 download links.\n'
} >> "$GITHUB_STEP_SUMMARY"
