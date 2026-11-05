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
from spot_vision.protocol import snapshot
from spot_vision.structs import RobotStatus, result_value


def generate(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    message = manifest()
    (root / "manifest.json").write_bytes(snapshot(message))
    (root / "profile.json").write_text(json.dumps(asdict(message), indent=2) + "\n")
    for name in ("empty", "multi", "ippe", "ambiguous"):
        observation = wire.Observation(
            capture_epoch="2" * 32,
            sequence=1,
            camera_name="front",
            calibration_valid=True,
            runtime_generation="1" * 32,
            robot_to_camera=message.profile.cameras[0].robot_to_camera.pose(),
            capture_local_nt_us=1_000_000,
            timestamp_source="read-completion-local-nt",
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
        (root / f"{name}.bin").write_bytes(pack(result_value(observation, message.profile.field)))
        if name == "multi":
            multi = copy.deepcopy(observation)
    multi.tag_selection_generation = 3
    (root / "policy-multi.bin").write_bytes(pack(result_value(multi, message.profile.field)))
    (root / "policy-state.bin").write_bytes(pack(RobotStatus(3, 3)))
    for name in ("ack.json", "policy-ack.json"):
        (root / name).unlink(missing_ok=True)


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "tests/data/robot")
