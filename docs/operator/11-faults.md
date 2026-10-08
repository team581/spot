Title: Faults and coordinates
Group: Reference

# Faults and coordinates

## Coordinate conventions

Wire translations are metres in WPILib NWU, quaternions are W/X/Y/Z, and poses are field-to-camera. The robot uses `fieldToCamera * inverse(robotToCamera)` to recover field-to-robot. OpenCV camera +X right, +Y down, +Z forward and tag-plane coordinates are converted explicitly by the existing pose solver. Blue-wall-right field origin stays fixed across alliance changes.

## Robot rejection meanings

SCHEMA/MALFORMED: unsupported or invalid bounded packet. CONFIGURATION/CALIBRATION: session, field, binding, active intrinsics or mode mismatch. TIMESTAMP/STALE/FUTURE: invalid capture domain, quality or age. DUPLICATE/OLD_EPOCH/RESET: frame identity or reset boundary. HISTORY/MOUNT_HISTORY: capture-time robot or moving-mount history unavailable. UNKNOWN_TAG/FIELD_BOUNDS/ROBOT_TILT: geometry is inconsistent. AMBIGUOUS: IPPE alternatives are not decisively resolved. RESIDUAL/INNOVATION: image or pre-fusion disagreement exceeds policy. NO_TAGS on a fresh valid observation is normal operation.

## Confidence and trust

Translation uncertainty uses conservative positive floors, distance, geometry conditioning, residual and motion × timestamp uncertainty. Cameras seeing the same tags in a short interval are correlated; additional observations cannot automatically count as independent certainty. Heading is suppressed with a large finite supported deviation until its separate review gate passes.

Revised trust evaluates each observation at its own capture time before fusion, degrades with actual odometry travel, elapsed time and collisions, and uses a consistent reset baseline. It remains behind a reviewed feature flag. Empty measurement lists never sample pose history at NaN. No history path substitutes the current pose to conceal missing capture-time evidence.
