Title: 3. Set camera geometry
Group: Getting started

# Set camera geometry

## Measure the mount

Use WPILib NWU: +X forward, +Y left, +Z up. Measure the camera optical origin in the robot frame in metres. Record the optical-axis yaw, pitch and roll with right-handed angles. Robot code constructs `Rotation3d(roll, pitch, yaw)` in radians; the GUI displays Yaw, Pitch, Roll in degrees, with positive Pitch pointing the lens down and negative Pitch pointing it up. All displayed angles retain their native WPILib signs. A camera looking forward has its NWU +X axis along the lens direction.

Do not use the visual reference's sample coordinates as measured mounts. The drivebase outline in the viewer is schematic, while the camera transform comes from the actual manifest.

## Inspect the transform

1. Open the named camera's **Geometry** tab.
2. Compare X/Y/Z and Yaw/Pitch/Roll with the measured code values, reversing the sign of code pitch for the displayed Pitch. Use the Front and Lens arrows to check signs and direction.
3. Orbit by pointer drag or Arrow keys. Use wheel or +/− for zoom and **Reset view** to return to the initial view.
4. Enable **Inspection preview** to explore finite edits. This is labelled inspection and does not alter robot geometry. Production transforms remain pinned by robot code; update measured code values and deploy a new robot profile to change them.

## Number editing

Click where the caret should go. Empty text, minus signs and partial decimals remain editable without becoming zero. Finite text updates the preview. Enter or blur validates one commit; Escape restores the acknowledged value. A conflict preserves the edit buffer. Values are not reformatted on each keystroke, and scrolling does not change them.

ArrowUp/ArrowDown and the steppers use 0.01 m or 1°. Shift uses 0.1 m or 10°; Alt uses 0.001 m or 0.1°. Native text undo/redo remains available during typing. The borderless history buttons represent acknowledged production configuration; they remain disabled for pinned geometry.

Fixed cameras use measured constant mounts. Moving cameras require capture-time joint history and full moving-mount qualification. Never substitute the current joint angle for a capture-time transform.
