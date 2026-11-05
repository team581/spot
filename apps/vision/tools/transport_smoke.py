#!/usr/bin/env python3
"""Publish synthetic estimates through Spot's real transport to a local Java reader."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import ntcore
import numpy as np

from spot_vision import protocol_models as wire
from spot_vision.clock import nt_now_us
from spot_vision.config import NtConfig
from spot_vision.configuration import ConfigurationService
from spot_vision.models import (
    DetectedFrame,
    Detection,
    DetectionBatch,
    FramePacket,
    PoseCandidate,
    PoseMethod,
    PoseSolution,
)
from spot_vision.nt_transport import NtTransport, make_observation
from spot_vision.persistence import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5810, help="local NT4 server port")
    parser.add_argument("--duration", type=float, default=10, help="maximum runtime in seconds")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 0 < args.duration <= 60:
        parser.error("port must be 1–65535 and duration must be greater than 0 and at most 60")

    with TemporaryDirectory(prefix="spot-transport-smoke-") as state:
        configuration = ConfigurationService(StateStore(Path(state)), lambda *_: None)

        def cameras():
            manifest = configuration.manifest
            return (
                [
                    wire.CameraGeneration(
                        camera_name=camera.name,
                        binding_id="synthetic-" + camera.name,
                        binding_generation=1,
                        calibration_hash="synthetic-smoke-calibration",
                        mode_id="synthetic-smoke-mode",
                        optical_signature="synthetic-smoke-lens",
                        calibration_valid=True,
                    )
                    for camera in manifest.profile.cameras
                    if camera.enabled
                ]
                if manifest
                else []
            )

        instance = ntcore.NetworkTableInstance.create()
        transport = NtTransport(
            NtConfig(server="127.0.0.1"), configuration, cameras, instance=instance
        )
        error = instance.getStringTopic("/Spot/config/acknowledgement/error").subscribe("")
        instance.setServer("127.0.0.1", args.port)
        instance.startClient4("spot-transport-smoke")
        sequence = 0
        published = 0
        print("SYNTHETIC transport smoke test; no cameras or production state", flush=True)
        try:
            deadline = time.monotonic() + args.duration
            while time.monotonic() < deadline:
                transport.poll()
                transport.heartbeat()
                selection = configuration.tag_selection()
                available = cameras()
                captured_ns = time.monotonic_ns()
                context = (
                    transport.context(available[0].camera_name, captured_ns, 0.001)
                    if available
                    else None
                )
                if context and selection and selection.allowed_tag_ids:
                    sequence += 1
                    tag_id = selection.allowed_tag_ids[0]
                    frame = FramePacket(
                        context.camera.camera_name,
                        sequence,
                        nt_now_us(),
                        captured_ns,
                        np.empty((480, 640), dtype=np.uint8),
                        capture_epoch="synthetic-transport-smoke",
                    )
                    detection = Detection(
                        tag_id,
                        np.array([[200.0, 150.0], [300.0, 150.0], [300.0, 250.0], [200.0, 250.0]]),
                    )
                    solution = PoseSolution(
                        candidates=(
                            PoseCandidate(
                                PoseMethod.SINGLE_TAG_IPPE_SQUARE,
                                np.array([2.25, 3.5, 0.75]),
                                np.array([1.0, 0.0, 0.0, 0.0]),
                                0.2,
                                (tag_id,),
                                average_tag_distance_m=2.0,
                            ),
                        )
                    )
                    observation = make_observation(
                        DetectedFrame(frame, DetectionBatch((detection,), 1.0), 0.0),
                        solution,
                        context,
                        1.0,
                        selection=selection,
                    )
                    if transport.publish(observation, captured_ns):
                        published += 1
                        print(
                            json.dumps(
                                {
                                    "sequence": sequence,
                                    "capture_local_us": frame.capture_timestamp_us,
                                    "capture_server_us": frame.capture_timestamp_us
                                    + transport.clock.snapshot().offset_us,
                                }
                            ),
                            flush=True,
                        )
                instance.flush()
                time.sleep(0.05)
            if published == 0:
                print(
                    f"Clock: {transport.clock.snapshot()}; profile fresh: {configuration.fresh}; "
                    f"configuration error: {error.get()}",
                    flush=True,
                )
        finally:
            error.close()
            transport.close()
            instance.stopClient()
            ntcore.NetworkTableInstance.destroy(instance)
        if published == 0:
            print(
                "No estimates published: check the local reader, profile, clock and tag selection."
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
