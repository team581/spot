Title: 1. Connect to Spot
Group: Getting started

# Connect to Spot

## Prerequisites

Use the installed beta release on the Spot Jetson, a powered USB hub and an Ethernet connection to the robot network. The roboRIO runs the NT4 server; Spot connects as an NT4 client. Fusion stays off until the hardware qualification record passes. Alpha commands are development tools and do not start this GUI.

## Install and connect

1. On the Jetson, install build prerequisites described in the repository README, then run `sudo deploy/install.sh /home/team581/spot-2026` from the source checkout. The installer builds a CUDA wheel, verifies its native module, and prints its immutable release ID.
2. Review `/etc/spot-vision/beta.json`. The packaged default uses team 581 discovery and HTTP port 5800. Set an explicit `nt.server` instead of `nt.team` when a different endpoint is required. Endpoint changes are administrator installation settings. The GUI does not change operating-system addresses.
3. For initial setup with hardware qualification pending, run `sudo /opt/spot-vision/activate.py RELEASE_ID --setup-only`. For a qualified disabled robot, omit `--setup-only` to require robot/profile/camera/timing readiness. The installer preserves `/var/lib/spot-vision` during activation and rollback.
4. Open `http://spot.local:5800` or the Jetson's actual local address and port. Network lists the local addresses. The GUI starts independently of camera or robot availability.
5. Open Network. Confirm the robot endpoint, NT connection, synchronized clock and current robot profile. Connect the USB cameras. Their physical feeds appear under Cameras.

The repository's dedicated maintenance connection is `ssh -i ~/.ssh/spot_jetson_ed25519 team581@192.168.69.170`. For direct Ethernet, the development Mac uses 192.168.69.171/24 on the connected adapter. These maintenance addresses are not a claim about the robot NT endpoint.

## Observable results

A disconnected robot still allows previews and saved calibration inspection. Configuration controls stay locked until a fresh disabled RobotState arrives, or you explicitly click **Begin standalone setup** on Network while the link is known disconnected. Connecting a robot ends standalone setup. Unknown enabled state never unlocks controls automatically.

Proceed to **2. Name cameras** after matching physical feeds to the intended robot camera definitions.
