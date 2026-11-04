#!/usr/bin/env bash
set -euo pipefail

# Install a built artifact with the workspace's locked runtime dependencies.
source_dir=${1:?Usage: install-wheel.sh /absolute/source /absolute/wheel /absolute/venv}
wheel_path=${2:?Wheel path required}
environment_dir=${3:?Virtual environment path required}
uv_bin=${SPOT_UV:-uv}
python_bin=${SPOT_PYTHON:-python3}

UV_PROJECT_ENVIRONMENT="$environment_dir" "$uv_bin" sync --project "$source_dir" \
  --locked --package spot-vision --no-dev --extra nt --extra systemd \
  --no-install-workspace --python "$python_bin" --no-python-downloads
"$uv_bin" pip install --python "$environment_dir/bin/python" --no-deps "$wheel_path"
"$uv_bin" pip check --python "$environment_dir/bin/python"
