"""Regenerate synthetic Python/Java WPILib struct fixtures.

Run with PYTHONPATH=apps/vision/src:apps/vision/tests. No hardware values or acceptance evidence.
"""

import copy
import json
from dataclasses import asdict
from pathlib import Path

from wpiutil.wpistruct import pack

from robot_fixtures import manifest
from spot_vision import protocol_models as wire
from spot_vision.contract import content_hash
from spot_vision.protocol import snapshot
from spot_vision.structs import RobotStatus, frame_context, result_value, token


def generate(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    message = manifest()
    (root / "manifest.json").write_bytes(snapshot(message))
    (root / "profile.json").write_text(json.dumps(asdict(message), indent=2) + "\n")
    camera = wire.CameraGeneration(
        camera_name="front",
        binding_id="usb-a",
        binding_generation=1,
        calibration_hash="a" * 64,
        calibration_valid=True,
        mode_id="640x480",
        optical_signature="fixed-lens-1",
    )
    ack = wire.Acknowledgement(
        robot_id=message.profile.robot_id,
        robot_session=message.robot_session,
        manifest_hash=message.manifest_hash,
        field_hash=content_hash(message.profile.field),
        service_session="service-1",
        connection_epoch=1,
        sync_epoch=2,
        runtime_generation="generation-1",
        cameras=[camera],
        applied=True,
    )
    (root / "ack.json").write_bytes(snapshot(ack))
    for name in ("empty", "multi", "ippe", "ambiguous"):
        observation = wire.Observation(
            robot_id=ack.robot_id,
            robot_session=ack.robot_session,
            service_session=ack.service_session,
            capture_epoch="capture-1",
            connection_epoch=1,
            sync_epoch=2,
            sequence=1,
            camera_name="front",
            binding_id="usb-a",
            binding_generation=1,
            manifest_hash=ack.manifest_hash,
            field_hash=ack.field_hash,
            calibration_hash=camera.calibration_hash,
            calibration_valid=True,
            runtime_generation=ack.runtime_generation,
            mode_id=camera.mode_id,
            optical_signature=camera.optical_signature,
            capture_local_nt_us=1_000_000,
            timestamp_source="read-completion-local-nt",
            timestamp_uncertainty_s=0.003,
        )
        if name != "empty":
            observation.tags.append(
                wire.TagObservation(id=1, corners_xy_px=[10, 10, 50, 10, 50, 50, 10, 50])
            )
            if name == "multi":
                observation.tags.append(
                    wire.TagObservation(id=2, corners_xy_px=[60, 10, 100, 10, 100, 50, 60, 50])
                )
            candidate = wire.PoseCandidate(
                field_to_camera=wire.Pose(x_m=2.2, z_m=0.5, qw=1),
                method=1 if name == "multi" else 2,
                tag_ids=[1, 2] if name == "multi" else [1],
                reprojection_error_px=0.2,
                average_tag_distance_m=2,
                image_area_fraction=0.04,
                image_spread_fraction=0.1,
            )
            observation.candidates.append(candidate)
            if name != "multi":
                import math

                alternative = copy.deepcopy(candidate)
                observation.candidates.append(alternative)
                yaw = 0.7
                if name == "ambiguous":
                    candidate.field_to_camera.qw = math.cos(0.1 / 2)
                    candidate.field_to_camera.qz = math.sin(0.1 / 2)
                    yaw = -0.1
                alternative.field_to_camera.qw = math.cos(yaw / 2)
                alternative.field_to_camera.qz = math.sin(yaw / 2)
        (root / f"{name}.bin").write_bytes(
            pack(
                result_value(
                    observation, frame_context(ack, observation.camera_name), message.profile.field
                )
            )
        )
        if name == "multi":
            multi = copy.deepcopy(observation)
    policy_ack = copy.deepcopy(ack)
    policy_ack.tag_selection_supported = True
    (root / "policy-ack.json").write_bytes(snapshot(policy_ack))
    multi.tag_selection_generation = 3
    (root / "policy-multi.bin").write_bytes(
        pack(
            result_value(multi, frame_context(policy_ack, multi.camera_name), message.profile.field)
        )
    )
    (root / "policy-state.bin").write_bytes(pack(RobotStatus(*token("robot-1"), True, 7, 3, 3)))


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "tests/data/robot")
