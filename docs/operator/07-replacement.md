Title: Replace a camera
Group: Guides

# Replace a camera

## Replacement procedure

1. Disable the robot or begin explicit standalone setup with a known disconnected link.
2. Identify the connected physical feed and its persistent ID. For duplicate/missing serials, confirm the labelled USB port.
3. In the named camera's Advanced controls, select the connected replacement device, check **I confirmed the replacement feed**, then click **Replace camera**. This bumps the binding generation and invalidates calibration for that physical identity, including a replacement reporting the same serial.
4. If the replacement has a different identity, select that identity in the existing named camera’s Advanced replacement picker; do not guess from video-node order.
5. Verify the optical mode and controls, recalibrate with a separate validation set, and repeat measured timing/pose qualification.

## Preserved and invalidated data

Logical names and robot-code transforms remain robot authority. Discovery inventory and physical bindings survive service restart. A compatible physical calibration can survive ordinary rename; a replacement requires fresh physical evidence. History restore checks identity, optical mode, orientation and optical controls before activating anything.
