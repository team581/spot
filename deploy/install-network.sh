#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Run this installer with sudo." >&2; exit 1; fi
source_dir=${1:?Usage: sudo deploy/install-network.sh /absolute/spot/source}
for executable in nmcli busctl avahi-daemon; do
  command -v "$executable" >/dev/null || { echo "Install NetworkManager and avahi-daemon before installing Spot networking." >&2; exit 1; }
done
getent group spot-vision >/dev/null || { echo "Install the Spot service account first." >&2; exit 1; }
backup=$(mktemp -d /opt/spot-vision/network-backup.XXXXXXXX)
for file in /opt/spot-vision/networking.py /etc/systemd/system/spot-network.service /etc/systemd/system/spot-network.socket /etc/avahi/avahi-daemon.conf /etc/avahi/services/spot.service; do
  if [[ -f "$file" ]]; then
    install -D -m 0600 "$file" "$backup$file"
    echo "restore $file from $backup$file" >> "$backup/manifest.txt"
  else
    echo "new $file" >> "$backup/manifest.txt"
  fi
done
systemctl is-enabled avahi-daemon.service > "$backup/avahi-enabled.txt" 2>&1 || true
systemctl is-active avahi-daemon.service > "$backup/avahi-active.txt" 2>&1 || true
install -o root -g root -m 0644 "$source_dir/src/spot_vision/networking.py" /opt/spot-vision/networking.py
install -o root -g root -m 0644 "$source_dir/deploy/spot-network.service" /etc/systemd/system/spot-network.service
install -o root -g root -m 0644 "$source_dir/deploy/spot-network.socket" /etc/systemd/system/spot-network.socket
python3 - <<'PY'
import json,re,subprocess
from pathlib import Path
# A multi-homed laptop may otherwise resolve Spot through an unrelated or
# unreliable Jetson Wi-Fi link even while the maintenance cable works.
interfaces=sorted(p.name for p in Path('/sys/class/net').iterdir()
    if (p/'device').exists() and subprocess.check_output(
        ['nmcli','-g','GENERAL.TYPE','device','show',p.name],text=True).strip()=='ethernet')
if not interfaces: raise SystemExit('Spot discovery requires a physical Ethernet interface')
settings={'host-name':'spot','allow-interfaces':','.join(interfaces)}
path=Path('/etc/avahi/avahi-daemon.conf')
lines=path.read_text().splitlines();output=[];in_server=False;written=set();found_server=False
for line in lines:
    if line.strip().startswith('['):
        if in_server:
            output.extend(f'{key}={value}' for key,value in settings.items() if key not in written)
            written.update(settings)
        in_server=line.strip()=='[server]'
        found_server |= in_server
    match=re.match(r'^\s*([a-z-]+)\s*=',line) if in_server else None
    if match and match[1] in settings:
        key=match[1]
        if key not in written: output.append(f'{key}={settings[key]}');written.add(key)
    else:output.append(line)
if not found_server:output.append('[server]')
if in_server or not found_server:
    output.extend(f'{key}={value}' for key,value in settings.items() if key not in written)
path.write_text('\n'.join(output)+'\n')
config=Path('/etc/spot-vision/beta.json')
port=json.loads(config.read_text()).get('http',{}).get('port',5800) if config.exists() else 5800
if type(port) is not int or not 1<=port<=65535: raise SystemExit('Invalid Spot HTTP port')
Path('/etc/avahi/services').mkdir(exist_ok=True)
Path('/etc/avahi/services/spot.service').write_text(f'''<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group><name replace-wildcards="yes">Spot on %h</name><service>
<type>_http._tcp</type><port>{port}</port><txt-record>path=/</txt-record>
</service></service-group>\n''')
PY
systemctl daemon-reload
systemctl enable --now avahi-daemon.service spot-network.socket
systemctl restart avahi-daemon.service
# Restart only the independent helper; an active NM checkpoint survives this.
if systemctl is-active --quiet spot-network.service; then systemctl restart spot-network.service; fi
echo "Installed Spot Ethernet controls and local discovery. Backup: $backup"
echo "No Ethernet addresses were changed. Open Network in Spot to choose DHCP or Static."
