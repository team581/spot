"""Synthetic, known transforms for Spot tests; never production defaults."""

import copy
from dataclasses import replace

from spot_vision import protocol_models as wire


def manifest():
    profile = wire.Profile(
        max_age_s=0.25,
        future_tolerance_s=0.005,
    )
    camera = wire.CameraDefinition(
        name="front",
        required=True,
        robot_to_camera=wire.Mount(x_m=0.2, z_m=0.5),
        allowed_modes=[
            wire.OpticalMode(
                id="640x480",
                width=640,
                height=480,
                pixel_format="MJPEG",
                fps=30,
            )
        ],
    )
    camera.detector = replace(camera.detector, backend="cpu")
    profile.cameras.append(camera)
    camera.controls.append(wire.ControlPolicy(name="gain", default_value=1, allow_override=True))
    camera.controls.append(
        wire.ControlPolicy(name="contrast", default_value=16, allow_override=False)
    )
    profile.field = copy.deepcopy(
        wire.FieldLayout(origin="blue-wall-right", length_m=16, width_m=8)
    )
    profile.field.tags.append(
        wire.FieldTag(id=1, size_m=0.1651, field_to_tag=wire.Pose(x_m=4, z_m=1, qw=1))
    )
    profile.field.tags.append(
        wire.FieldTag(id=2, size_m=0.1651, field_to_tag=wire.Pose(x_m=5, y_m=1, z_m=1, qw=1))
    )
    return wire.Manifest(profile=profile)


class RobotPublisher:
    """Publish robot defaults through the production JSON/typed NT boundary."""

    def __init__(self, nt, options):
        self.nt, self.options, self.publishers = nt, options, {}

    def put(self, path, value, kind=None):
        if path not in self.publishers:
            kind = kind or (
                "Boolean"
                if isinstance(value, bool)
                else "Double"
                if isinstance(value, (int, float))
                else "String"
            )
            self.publishers[path] = getattr(self.nt, "get" + kind + "Topic")(
                "/Spot/Config/" + path
            ).publish(self.options)
        self.publishers[path].set(value)

    def set(self, message):
        from spot_vision.protocol import snapshot
        from spot_vision.structs import FieldTag, pose_value

        p = message.profile
        self.put(
            "cameraConfig", snapshot(wire.RobotConfiguration(p.cameras, p.processing)).decode()
        )
        for key, value in (
            ("maxAgeS", p.max_age_s),
            ("futureToleranceS", p.future_tolerance_s),
            ("Field/origin", p.field.origin),
            ("Field/lengthM", p.field.length_m),
            ("Field/widthM", p.field.width_m),
        ):
            self.put(key, value)
        if "Field/tags" not in self.publishers:
            self.publishers["Field/tags"] = self.nt.getStructArrayTopic(
                "/Spot/Config/Field/tags", FieldTag
            ).publish(self.options)
        self.publishers["Field/tags"].set(
            [FieldTag(t.id, pose_value(t.field_to_tag), t.size_m) for t in p.field.tags]
        )

    def close(self):
        for pub in self.publishers.values():
            pub.close()


class StatePublisher:
    def __init__(self, nt, options):
        from spot_vision.structs import RobotStatus

        self.publisher = nt.getStructTopic("/Spot/robot/state", RobotStatus).publish(options)

    def set(self, state):
        from spot_vision.structs import RobotStatus, tag_mask

        self.publisher.set(
            RobotStatus(
                state.tag_selection_generation,
                tag_mask(state.allowed_tag_ids, manifest().profile.field),
            )
        )

    def close(self):
        self.publisher.close()
