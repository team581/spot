#!/usr/bin/env bash
# Start or stop the macOS linux-builder VM in the background.
set -euo pipefail

flake="path:$(cd "$(dirname "$0")/.." && pwd)"
dir=~/.local/share/linux-builder
mkdir -p "$dir"
cd "$dir"

running() { nc -z 127.0.0.1 31022 2>/dev/null; }

if [ "${1:-start}" = stop ]; then
  if running; then
    echo system_powerdown | nc -U monitor.sock >/dev/null
    while running; do sleep 1; done
  fi
  exit
fi

if ! running; then
  # Installs the VM's SSH key with sudo on the first run.
  nix run "$flake#linux-builder.add-keys"
  echo "Starting the linux-builder VM; its console log is $dir/console.log"
  QEMU_OPTS="-monitor unix:$dir/monitor.sock,server,nowait" \
    nohup nix run "$flake#linux-builder.run-builder" >console.log 2>&1 </dev/null &
fi

for _ in $(seq 180); do
  if [ -n "$(ssh-keyscan -T 1 -p 31022 127.0.0.1 2>/dev/null)" ]; then exit; fi
  sleep 1
done
echo "The linux-builder VM didn't start; see $dir/console.log" >&2
exit 1
