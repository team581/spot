#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  --help|-h)
    cat <<'HELP'
Usage: bash tools/jetson-ubuntu-deploy.sh

Temporary deployment to the already-configured Ubuntu / JetPack 6 Jetson.
Copies tracked working-tree files, builds on the Jetson, and restarts Spot.
No local Nix or Docker is used. Add new files to Git before deploying.
Pause calibration first; deployment restarts the service.

SPOT_HOST                 Jetson address (default: 10.99.91.11)
SPOT_SSH_CONTROL_SOCKET   Reuse an SSH master that forwards remote SOCKS :11080.
                          Otherwise this script opens and closes its own tunnel.
HELP
    exit 0
    ;;
  "") ;;
  *) echo "Unexpected argument: $1. Use --help." >&2; exit 2 ;;
esac

source_dir=$(cd "$(dirname "$0")/.." && pwd)
test -f "$source_dir/jetpack/flake.nix" || {
  echo "This workaround requires the temporary JetPack 6 branch." >&2
  exit 1
}
stage=$(mktemp -d /tmp/spot-ubuntu-deploy.XXXXXX)
control=${SPOT_SSH_CONTROL_SOCKET:-$stage/ssh}
owns_control=false
ssh_jetson() { bash "$source_dir/tools/jetson-ssh.sh" -S "$control" "$@"; }
cleanup() {
  if "$owns_control"; then ssh_jetson -O exit >/dev/null 2>&1 || true; fi
  rm -rf -- "$stage"
}
trap cleanup EXIT

if [ -n "${SPOT_SSH_CONTROL_SOCKET:-}" ]; then
  ssh_jetson -O check
else
  bash "$source_dir/tools/jetson-ssh.sh" -M -S "$control" \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
    -R 127.0.0.1:11080 -fN
  owns_control=true
fi

revision=$(git -C "$source_dir" rev-parse HEAD)
if ! git -C "$source_dir" diff --quiet HEAD --; then revision="$revision-dirty"; fi
git -C "$source_dir" ls-files -z > "$stage/files"
COPYFILE_DISABLE=1 tar --no-xattrs -C "$source_dir" -czf "$stage/source.tar.gz" --null -T "$stage/files"
remote_source=$(ssh_jetson 'mktemp -d /home/team581/spot-ubuntu-deploy.XXXXXX')
[[ "$remote_source" =~ ^/home/team581/spot-ubuntu-deploy\.[a-zA-Z0-9]+$ ]]
ssh_jetson "tar -xzf - -C '$remote_source'" < "$stage/source.tar.gz"

# A root local-store client uses this SSH proxy directly, without restarting
# the host's Nix daemon or requiring persistent Internet sharing.
ssh_jetson sudo -n env NIX_REMOTE=local \
  ALL_PROXY=socks5h://127.0.0.1:11080 all_proxy=socks5h://127.0.0.1:11080 \
  bash -s -- "$remote_source" "$revision" <<'REMOTE'
set -euo pipefail
source_dir=$1
revision=$2
nix=/nix/var/nix/profiles/default/bin/nix
profile=/opt/spot-vision/nix-profile
dropin=/etc/systemd/system/spot-vision.service.d/90-nix-package.conf
test "$(uname -m)" = aarch64
test -x "$nix"
test -f "$dropin"
test -L "$profile"
cd "$source_dir"

"$nix" build path:.#packages.aarch64-linux.spot-vision \
  --override-input jetpack "path:$source_dir/jetpack" \
  --out-link result --max-jobs 1 --cores 2 -L
app=$(readlink -f result)
mkdir smoke
"$app/bin/python" apps/vision/tests/installed_service.py --smoke-cuda "$app" "$source_dir/smoke"

old_link=$(basename "$(readlink "$profile")")
old_generation=${old_link#nix-profile-}
old_generation=${old_generation%-link}
[[ "$old_generation" =~ ^[0-9]+$ ]]
backup="/var/backups/spot-$(basename "$source_dir")"
mkdir -m 0700 "$backup"
cp "$dropin" "$backup/service.conf"
rollback() {
  result=$?
  if [ "$result" -ne 0 ]; then
    trap - EXIT
    "$nix" profile rollback --profile "$profile" --to "$old_generation"
    cp "$backup/service.conf" "$dropin"
    systemctl daemon-reload
    systemctl restart spot-vision
    echo "Deployment failed; restored profile generation $old_generation." >&2
    exit "$result"
  fi
}
systemctl stop spot-vision
trap rollback EXIT
tar -czf "$backup/state.tar.gz" -C / var/lib/spot-vision-nix
"$nix" profile remove --profile "$profile" spot-vision
"$nix" profile add --profile "$profile" "$app"
sed -i "s/^Environment=SPOT_CONFIGURATION_REVISION=.*/Environment=SPOT_CONFIGURATION_REVISION=$revision/" "$dropin"
systemctl daemon-reload
systemctl restart spot-vision
"$profile/bin/spot-vision" check-health --timeout 45
echo "Deployed $revision; previous profile generation: $old_generation"
echo "Unit and state backup: $backup"
echo "Remote source retained: $source_dir"
REMOTE
