"""Synthetic, known transforms for beta tests; never production defaults."""

from spot_vision.beta_contract import content_hash
from spot_vision.proto import vision_v2_pb2 as wire


def manifest(robot_id="test-robot", session="robot-1"):
    profile = wire.Profile(
        schema_version=2,
        robot_id=robot_id,
        max_age_s=0.25,
        future_tolerance_s=0.005,
        reorder_window_s=0.02,
    )
    camera = profile.cameras.add(name="front", enabled=True, required=True)
    camera.robot_to_camera.CopyFrom(wire.Pose(x_m=0.2, z_m=0.5, qw=1))
    camera.allowed_modes.add(
        id="640x480",
        width=640,
        height=480,
        pixel_format="MJPG",
        fps=30,
        optical_signature="fixed-lens-1",
    )
    camera.controls.add(name="gain", default_value=1, allow_override=True)
    camera.controls.add(name="contrast", default_value=16, allow_override=False)
    profile.field.CopyFrom(wire.FieldLayout(origin="blue-wall-right", length_m=16, width_m=8))
    profile.field.tags.add(id=1, size_m=0.1651, field_to_tag=wire.Pose(x_m=4, z_m=1, qw=1))
    profile.field.tags.add(id=2, size_m=0.1651, field_to_tag=wire.Pose(x_m=5, y_m=1, z_m=1, qw=1))
    return wire.Manifest(
        profile=profile, robot_session=session, manifest_hash=content_hash(profile)
    )
