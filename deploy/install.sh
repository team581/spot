#!/usr/bin/env bash
set -euo pipefail

# Build/install an immutable release. Activation is a separate, verified step.
if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi
source_dir=${1:?Usage: sudo deploy/install.sh /absolute/spot/source}
if [[ ! -f "$source_dir/pyproject.toml" ]]; then
  echo "Spot source was not found at $source_dir" >&2
  exit 1
fi
if [[ ! -f "$source_dir/dist/jetson-docs/index.html" || ! -f "$source_dir/dist/jetson-docs/pagefind/pagefind.js" ]]; then
  echo "Build documentation before installing: pnpm --dir $source_dir/docs-site build:jetson" >&2
  exit 1
fi
if ! id spot-vision >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin spot-vision
fi
usermod -a -G video spot-vision
if getent group render >/dev/null; then
  usermod -a -G render spot-vision
fi
install -d -o root -g spot-vision -m 0750 /etc/spot-vision
install -d -o spot-vision -g spot-vision -m 0750 /var/lib/spot-vision
install -d -o root -g root -m 0755 /opt/spot-vision/releases
"$source_dir/deploy/install-network.sh" "$source_dir"
build_dir=$(mktemp -d /var/tmp/spot-release.XXXXXXXX)
trap 'rm -rf "$build_dir"' EXIT
python3 -m venv "$build_dir/build-env"
"$build_dir/build-env/bin/python" -m pip install --upgrade pip
CMAKE_ARGS="-DSPOT_BUILD_CUDA=ON -DSPOT_CUDA_ARCHITECTURES=87" \
  "$build_dir/build-env/bin/python" -m pip wheel --no-deps "$source_dir" -w "$build_dir/wheels"
wheel_path=$(find "$build_dir/wheels" -maxdepth 1 -name 'spot_vision-*.whl' -print -quit)
release_id=$("$build_dir/build-env/bin/python" - "$wheel_path" <<'PY'
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as wheel:
    manifest = json.loads(wheel.read('spot_vision/build-manifest.json'))
    if not manifest['native_cuda']:
        raise SystemExit('Production installer requires a CUDA wheel')
    print(manifest['release_id'])
PY
)
if [[ ! "$release_id" =~ ^[a-f0-9]{16}$ ]]; then
  echo "Invalid built release identity" >&2
  exit 1
fi
release_dir="/opt/spot-vision/releases/$release_id"
if [[ -e "$release_dir" ]]; then
  echo "Release already installed: $release_dir" >&2
  exit 1
fi
install -d -o root -g root -m 0755 "$release_dir"
python3 -m venv "$release_dir/.venv"
"$release_dir/.venv/bin/python" -m pip install "$wheel_path" 'pyntcore>=2026.2.2,<2027' 'robotpy-wpimath>=2026.2.2,<2027' 'sdnotify>=0.3.2'
"$release_dir/.venv/bin/python" -m pip freeze > "$release_dir/dependencies.txt"
"$release_dir/.venv/bin/spot-vision" verify-release --backend cuda > "$release_dir/verified-artifacts.json"
cp "$wheel_path" "$release_dir/"
chmod -R a-w "$release_dir"
if [[ ! -f /etc/spot-vision/beta.json ]]; then
  install -o root -g spot-vision -m 0640 "$source_dir/config/beta-installation.json" /etc/spot-vision/beta.json
else
  install -o root -g spot-vision -m 0640 "$source_dir/config/beta-installation.json" /etc/spot-vision/beta.json.new
  echo "Existing installation settings retained; review /etc/spot-vision/beta.json.new"
fi
install -o root -g root -m 0644 "$source_dir/deploy/spot-vision.service" /etc/systemd/system/spot-vision.service
install -o root -g root -m 0755 "$source_dir/deploy/activate.py" /opt/spot-vision/activate.py
systemctl daemon-reload
systemctl enable spot-vision.service
echo "Installed $release_id; service has not been switched."
echo "Activate: sudo /opt/spot-vision/activate.py $release_id"
echo "For initial offline setup only, add --setup-only. Robot qualification remains pending."
