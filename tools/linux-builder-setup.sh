#!/usr/bin/env bash
# Configure Nix on macOS to send Linux builds to the VM started by `mise run linux-builder`.
set -euo pipefail

# The fixed SSH host key that nixpkgs bakes into darwin.linux-builder.
host_key=c3NoLWVkMjU1MTkgQUFBQUMzTnphQzFsWkRJMU5URTVBQUFBSUpCV2N4Yi9CbGFxdDFhdU90RStGOFFVV3JVb3RpQzVxQkorVXVFV2RWQ2Igcm9vdEBuaXhvcwo=

sudo tee /etc/ssh/ssh_config.d/100-linux-builder.conf >/dev/null <<'EOF'
Host linux-builder
  Hostname localhost
  HostKeyAlias linux-builder
  Port 31022
EOF

# Determinate Nix overwrites nix.conf, so its custom settings go in nix.custom.conf.
conf=/etc/nix/nix.custom.conf
[ -e "$conf" ] || conf=/etc/nix/nix.conf
if ! grep -q 'builder@linux-builder' "$conf"; then
  sudo tee -a "$conf" >/dev/null <<EOF
builders = ssh-ng://builder@linux-builder aarch64-linux /etc/nix/builder_ed25519 4 1 benchmark,big-parallel - $host_key
builders-use-substitutes = true
EOF
fi

if [ -d /etc/determinate ]; then
  # Determinate's Native Linux Builder can't build jetpack-nixos, so keep it from taking jobs.
  config=/etc/determinate/config.json
  if [ ! -e "$config" ]; then
    echo '{"builder":{"state":"disabled"}}' | sudo tee "$config" >/dev/null
  elif ! sudo plutil -replace builder.state -string disabled "$config" 2>/dev/null; then
    sudo plutil -insert builder -json '{"state":"disabled"}' "$config"
  fi
  sudo launchctl kickstart -k system/systems.determinate.nix-daemon
else
  sudo launchctl kickstart -k system/org.nixos.nix-daemon
fi
