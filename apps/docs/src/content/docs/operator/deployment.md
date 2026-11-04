---
title: 'Deployment / rollback'
---

Spot runs as a NixOS appliance. OS configuration, NVIDIA JetPack integration,
Python dependencies, CUDA detector, dashboard, and offline docs belong to one
pinned system generation. Calibration and assignments stay separately under
`/var/lib/spot-vision`.

## Connect

From any source checkout on a maintenance laptop, without Nix or internet access:

```sh
bash tools/jetson-ssh.sh
```

The repository contains the team's shared maintenance key. No separate credential
is required. For a direct Ethernet cable, assign the laptop
`192.168.69.171/24`; Spot initially uses `192.168.69.170`.

## Test and persist

For an existing NixOS installation, run from the repository root:

```sh
nix run .#deploy -- test
bash tools/jetson-ssh.sh spot-vision check-health --robot
nix run .#deploy -- switch
```

`test` builds on Spot and activates without changing the boot default.
`spot-vision check-health --robot` checks the running package, profile acknowledgement,
synchronized robot clock, and required camera calibration/timing/detection freshness. Keep the robot disabled and do not change
the checkout between test and switch.

For initial offline setup, use `spot-vision check-health`. Robot/camera
qualification remains pending. Spot uses systemd notification to report startup
after native loading, state initialization, and web server startup.

Use **System → Software** to record the NixOS system path, application package
path, configuration revision, version, and process start time. Wall-clock time
can be unavailable while offline; the Nix package identity remains available.

## Recover

Deployments do not automatically roll back. After a failed `test`, restore the
persistent boot generation:

```sh
bash tools/jetson-ssh.sh sudo /nix/var/nix/profiles/system/bin/switch-to-configuration test
```

After persisting a generation, return to the previous one:

```sh
bash tools/jetson-ssh.sh sudo nixos-rebuild switch --rollback
```

If SSH is unavailable, reboot into the unchanged boot default after a temporary
test, or select an older retained generation from the boot menu. Rollback
restores system/application configuration, not calibration state or firmware.

## Diagnostic evidence

```sh
bash tools/jetson-ssh.sh systemctl status spot-vision
bash tools/jetson-ssh.sh journalctl -u spot-vision -b
```

Use System to export a support bundle/configuration or record 10–30 seconds of
bounded diagnostics. Recording does not take camera ownership.

## Ethernet controls and discovery

NixOS configures NetworkManager, Avahi, the independent privileged helper, and
its group-restricted socket. Spot's camera service stays unprivileged. Discovery
advertises the shared Ethernet bridge, not Wi-Fi. Both Ethernet sockets provide
the same addresses and services. Choose Automatic or Static on
**Network → Jetson address**; the Nix-defined maintenance address is retained.
NetworkManager protects each trial with a 90-second rollback. Trial profiles stay
in memory until confirmation; one saved override survives reboot and deployment.

First OS installation, firmware requirements, offline transfer, and hardware
qualification are documented in `nix/README.md` in the repository. The target is
an Orin Nano 8GB on a Seeed reComputer Robotics J401_V1.0 carrier, with Seeed's
JetPack 7.2 firmware already installed. The J401 module preserves the firmware's
device tree. First NixOS boot and hardware qualification must be completed before
using it on the robot.
