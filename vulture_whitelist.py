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
has_configuration

# Pydantic, FastAPI and uvicorn read these attributes.
mode_id
model_config
_.route_class
_.should_exit

# test_health_checks.py serves a stub through http.server.
_.log_message
_.do_GET

# pybind11 reads these native configuration attributes.
_.k1
_.k2
_.k3
_.p1
_.p2

# Profile fields are read through dataclass serialization.
fusion_enabled
heading_enabled

# make_wpistruct generates field access at runtime for the robot's wire format.
# Removing these fields would change the shared Python/Java struct layouts.
reprojectionError
averageDistance
imageArea
imageSpread
revisionHigh
revisionLow
robotToCamera
calibrationValid
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
