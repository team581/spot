Title: Network and power recovery
Group: Guides

# Network and power recovery

## Ethernet or robot interruption

Spot keeps camera processing, previews and saved settings while the robot link is down. Observations are withheld and unsent backlog is discarded. Reconnect establishes new connection/time-sync epochs, refreshes the profile handshake, and releases only post-sync/post-acknowledgement frames. No component silently reseeds the estimator or clears accumulated trust degradation.

A new robot program has a new session and FPGA epoch. Cached profile equality is not a handshake. Unknown enabled state stays locked. Disconnect does not automatically enter standalone setup.

## Camera and hub interruption

Each capture owner uses bounded reads and retries its authorized profile. Rediscovery uses persistent serial/port identity, re-verifies mode and controls, and creates a new capture epoch. Unaffected cameras continue. Required missing cameras remain visible and produce robot faults; an optional absent camera degrades independently.

## Power and state corruption

Application state uses checksummed immutable generations with fsynced atomic pointers. An interrupted staged write cannot activate a partial group. Corrupt active state falls back to the previous complete generation with an explicit fault. Bad identity inventory disables production identity confidence rather than silently guessing.

Hardware sudden-power-loss boot reliability and filesystem health require physical tests. Review the plan's 1 s, 30 s and 5 min outages, repeated flapping, each startup order, USB/hub power loss and write interruption trials. The installed service starts the UI before waiting for USB or robot dependencies.

## Clock behavior

The NT4 client uses actual built-in NT synchronization events. Local monotonic time alone is not synchronization. NTCore 2026.2.2 only processes the initial offset exchange, so the engineering 30 s expiry requests a new built-in exchange by reconnecting. Hardware drift and latency trials must qualify this interval. Polling an unchanged offset never refreshes its validity.

## Detector recovery and processing load

Installation `processing.fallback_to_cpu` defaults to false. Strict CUDA verification always requires a CUDA build. When CPU fallback is explicitly enabled, a recoverable GPU error switches that camera to CPU once and records a new backend generation. At most three recovery probes run, 30 s apart; a successful probe supplies that exposure's single result and restores CUDA. A recurring failure exhausts the same retry budget until reconfiguration or service restart. Native crashes remain supervised service failures.

Fallback limits processing to 5 FPS per affected camera and reports degraded capacity. Thermal reduction enters at 80 °C, exits at 75 °C, and caps processing at 10 FPS. A shared processing budget scales all camera targets proportionally when measured detector/solver demand exceeds 80% of the single processing worker. Latest-frame slots stay bounded; capture and optical settings remain unchanged. System shows backend generation, target cadence and degradation reasons. These are explicit engineering defaults, not qualified Jetson performance. Hardware trials must validate or review them without weakening robot age gates.
