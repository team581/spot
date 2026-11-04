# Reviewed dynamic API usage; Vulture parses this file without executing it.
# Keep actual dead code out of this list. Names match globally, so each name
# appears once even when several libraries/tests use it.

# TypedDict keys are read through dictionary indexing, not attribute access.
# See devices.py's ControlCapability and persistent DeviceRegistry schemas.
writable
schema_version
display_ids
duplicate_serials
next_id
port_slots

# socketserver/http.server read these attributes and dispatch these methods.
daemon_threads
block_on_close
server_version
protocol_version
_.close_connection
_.log_message
_.do_GET
_.do_POST

# RobotPy and pybind11 read these native configuration attributes.
_.quadDecimate
_.quadSigma
_.numThreads
_.refineEdges
_.minClusterPixels
_.criticalAngle
_.k1
_.k2
_.k3
_.p1
_.p2

# Cross-language data-model fields populated by keyword and retained in
# dataclass snapshots. Keep these aligned with the Java protocol models.
fusion_enabled
heading_enabled
revised_trust_enabled
used_for_pose
rejection_reason
release_id
native_hash

# make_wpistruct generates field access at runtime for the robot's wire format.
# Removing these fields would change the shared Python/Java struct layouts.
reprojectionError
averageDistance
imageArea
imageSpread
contextHigh
contextLow
captureHigh
captureLow
captureLocalNtUs
timestampSource
timestampUncertainty
observedTags
alternate
captureToDetectMs
detectMs
solveMs
totalMs
serviceHigh
serviceLow
runtimeHigh
runtimeLow
uptime
syncState
offsetUs
syncAge
connectionEpoch
syncEpoch
