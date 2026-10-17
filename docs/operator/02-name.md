Title: 2. Name cameras
Group: Getting started

# Name cameras

## Before renaming

Robot code supplies the available names, modes, field layout, transforms and control policy. Naming binds a physical camera to one of these definitions. The offseason example initially has no Spot cameras because measured mounts have not been supplied. Add measured definitions in robot code, deploy the robot program, and confirm its current profile in Network.

## Identify and rename

1. Plug one camera into the powered hub. Open its warning entry, such as USB-01, in the sidebar.
2. Identify the physical camera from its preview. Cover its lens briefly or point it toward a distinguishable object. Do not use `/dev/videoN` order to identify a production camera.
3. In **Camera name**, choose the matching available code-defined **Name**. Cached names are explicitly identified when the robot is disconnected.
4. Click **Rename**. Wait for the backend acknowledgement. Confirm the sidebar name changes while the same physical feed remains selected.
5. Address the calibration warning using **4. Calibrate**. A compatible saved calibration follows the physical camera; renaming does not calibrate it.

## Missing or duplicate identities

USB labels and camera slots are saved against the physical USB path, including hub ports. The same port keeps its slot through service restarts and Jetson reboots, even if Linux assigns a different `/dev/videoN`. Moving a camera to another port uses that port's slot; returning it restores its original saved configuration. Keep the hub connected to the same upstream Jetson port to retain the same paths.

Serial numbers still distinguish physical devices within each slot, preventing a replacement with a different serial from silently inheriting a calibration. Missing or duplicate serials cannot distinguish otherwise identical replacements; confirm those replacements explicitly. When upgrading from a serial-based registry, the currently connected camera is pinned to its current port while retaining its existing identity and settings.

A name already bound to another device is unavailable. Use the replacement guide for a deliberate physical replacement. Names absent from robot code cannot be created by typing arbitrary text in the GUI.
