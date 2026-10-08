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

Unique serials follow the device between USB ports. Missing or duplicate serials bind to USB topology and keep their persistent display ID. Keep those cameras in their labelled ports. If a duplicate serial is discovered later, the identity becomes port based and requires explicit confirmation; the service never silently moves a production name.

A name already bound to another device is unavailable. Use the replacement guide for a deliberate physical replacement. Names absent from robot code cannot be created by typing arbitrary text in the GUI.
