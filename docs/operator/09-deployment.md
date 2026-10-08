Title: Deployment / rollback
Group: Guides

# Deployment and rollback

## Immutable releases

`deploy/install.sh SOURCE_DIRECTORY` builds a CUDA wheel, installs it under `/opt/spot-vision/releases/RELEASE_ID`, verifies the loaded native module and application assets, records dependency versions and makes application files read-only. It does not switch the running service automatically. State is writable only under `/var/lib/spot-vision`; `/etc/spot-vision` remains read-only to the service.

Activate with `sudo /opt/spot-vision/activate.py RELEASE_ID`. The script atomically switches `current`, restarts systemd, waits up to 120 s for installed HTTP/native identity and required robot readiness, and records the attempt separately from successful deployment. Use `--setup-only` explicitly for initial offline GUI setup; it records hardware qualification as pending.

## Rollback

If verification fails, activation restores the previous release link and restarts it. To deliberately restore an earlier compatible beta release, activate its existing ID with the same procedure. Assignments, calibrations and installation configuration stay outside release directories. Preserve the historical alpha installation before the first migration; an alpha wheel is not a beta release rollback target.

System distinguishes **Last successful deployment**, **Running release**, **Started**, latest attempt and rollback state. It reports the module actually loaded by the process. If wall time has not been verified by systemd timesync, calendar timestamps say **Time unavailable** while identity and monotonic uptime remain visible.

## Troubleshooting and support

Use `systemctl status spot-vision` and `journalctl -u spot-vision`. Default logs retain meaningful faults and transitions, avoiding per-frame arrays. System can export a support bundle and configuration or record 10–30 s of bounded diagnostic snapshots. A debug recording does not change camera ownership. Import checks the current code profile, physical identities, policy, mode and calibration before an atomic disabled-only acknowledgement.
