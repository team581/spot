#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

project_dir=${1:-/opt/buddy-vision}
if [[ ! -f "$project_dir/pyproject.toml" ]]; then
  echo "Buddy source was not found at $project_dir" >&2
  exit 1
fi

if ! id buddy-vision >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin buddy-vision
fi
usermod -a -G video buddy-vision

python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/pip" install --upgrade pip
CMAKE_ARGS=-DBUDDY_CUDA_ARCHITECTURES=87 \
  "$project_dir/.venv/bin/pip" install "$project_dir[systemd]"

install -d -o root -g buddy-vision -m 0750 /etc/buddy-vision
if [[ ! -f /etc/buddy-vision/buddy.json ]]; then
  install -o root -g buddy-vision -m 0640 "$project_dir/config/buddy.json" \
    /etc/buddy-vision/buddy.json
fi
install -o root -g root -m 0644 "$project_dir/deploy/buddy-vision.service" \
  /etc/systemd/system/buddy-vision.service
systemctl daemon-reload
systemctl enable buddy-vision.service

echo "Edit /etc/buddy-vision/buddy.json, then run: sudo systemctl start buddy-vision"
