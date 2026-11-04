# Reviewed dynamic API usage; Vulture parses this file without executing it.
# Keep actual dead code out of this list. Names match globally, so each name
# appears once even when several libraries/tests use it.

# TypedDict keys are read through dictionary indexing, not attribute access.
# See devices.py's capability/registry schemas and runtime_status.StatusSnapshot.
writable
schema_version
display_ids
duplicate_serials
next_id
port_slots
uptime_s

# socketserver/http.server read these attributes and dispatch these methods.
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

# Profile fields are read by dataclass hashing and snapshot serialization.
# ProfileSubscriber reads their NT values; SpotMetadata.java publishes them.
fusion_enabled
heading_enabled
revised_trust_enabled

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
uptime
offsetUs
syncAge
connectionEpoch
