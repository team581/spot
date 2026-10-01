#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

project_dir=${1:-/opt/spot-vision}
if [[ ! -f "$project_dir/pyproject.toml" ]]; then
  echo "Spot source was not found at $project_dir" >&2
  exit 1
fi

if ! id spot-vision >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin spot-vision
fi
usermod -a -G video spot-vision

python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/pip" install --upgrade pip
CMAKE_ARGS=-DSPOT_CUDA_ARCHITECTURES=87 \
  "$project_dir/.venv/bin/pip" install "$project_dir[nt,systemd]"

install -d -o root -g spot-vision -m 0750 /etc/spot-vision
install -o root -g spot-vision -m 0640 \
  "$project_dir/config/2026-rebuilt-welded.json" \
  "$project_dir/config/calibration-left.json" \
  "$project_dir/config/calibration-right.json" \
  /etc/spot-vision/
if [[ ! -f /etc/spot-vision/spot.json ]]; then
  install -o root -g spot-vision -m 0640 "$project_dir/config/spot.json" \
    /etc/spot-vision/spot.json
else
  install -o root -g spot-vision -m 0640 "$project_dir/config/spot.json" \
    /etc/spot-vision/spot.json.new
  echo "Existing /etc/spot-vision/spot.json preserved."
  echo "Review /etc/spot-vision/spot.json.new before replacing it."
fi
install -o root -g root -m 0644 "$project_dir/deploy/spot-vision.service" \
  /etc/systemd/system/spot-vision.service
systemctl daemon-reload
systemctl enable spot-vision.service

echo "Edit /etc/spot-vision/spot.json, then run: sudo systemctl start spot-vision"
