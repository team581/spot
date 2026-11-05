"""Synthetic, known transforms for Spot tests; never production defaults."""

import copy

from spot_vision import protocol_models as wire
from spot_vision.contract import content_hash


def manifest(robot_id="test-robot", session="robot-1"):
    profile = wire.Profile(
        robot_id=robot_id,
        max_age_s=0.25,
        future_tolerance_s=0.005,
        reorder_window_s=0.02,
    )
    camera = wire.CameraDefinition(name="front", enabled=True, required=True)
    profile.cameras.append(camera)
    camera.robot_to_camera = copy.deepcopy(wire.Pose(x_m=0.2, z_m=0.5, qw=1))
    camera.allowed_modes.append(
        wire.OpticalMode(
            id="640x480",
            width=640,
            height=480,
            pixel_format="MJPG",
            fps=30,
            optical_signature="fixed-lens-1",
        )
    )
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
    return wire.Manifest(
        profile=profile, robot_session=session, manifest_hash=content_hash(profile)
    )


class RobotPublisher:
    """Test robot peer publishing the same native topics as SpotMetadata.java."""

    def __init__(self, nt, options):
        self.nt, self.options, self.publishers = nt, options, {}
        self.header = nt.getStringTopic("/Spot/robot/manifest").publish(options)
        self.session = nt.getStringTopic("/Spot/robot/session").publish(options)

    def put(self, path, value, kind=None):
        if path not in self.publishers:
            kind = kind or (
                "Boolean"
                if isinstance(value, bool)
                else "Integer"
                if isinstance(value, int)
                else "Double"
                if isinstance(value, float)
                else "StringArray"
                if isinstance(value, list)
                else "String"
            )
            self.publishers[path] = getattr(self.nt, "get" + kind + "Topic")(
                "/Spot/robot/profile/" + path
            ).publish(self.options)
        self.publishers[path].set(value)

    def set(self, manifest):
        from dataclasses import asdict

        from wpimath.geometry import Transform3d

        from spot_vision.structs import FieldTag, pose_value

        profile = manifest.profile
        for key, value in asdict(profile).items():
            if key not in ("cameras", "field"):
                self.put(key, value, "Double" if key.endswith("_s") else None)
        self.put("field/origin", profile.field.origin)
        self.put("field/length_m", profile.field.length_m, "Double")
        self.put("field/width_m", profile.field.width_m, "Double")
        if "field/tags" not in self.publishers:
            self.publishers["field/tags"] = self.nt.getStructArrayTopic(
                "/Spot/robot/profile/field/tags", FieldTag
            ).publish(self.options)
        self.publishers["field/tags"].set(
            [FieldTag(t.id, pose_value(t.field_to_tag), t.size_m) for t in profile.field.tags]
        )
        for camera in profile.cameras:
            p = "cameras/" + camera.name + "/"
            for key in ("required", "enabled", "image_rotation_deg"):
                self.put(p + key, getattr(camera, key))
            if p + "robot_to_camera" not in self.publishers:
                self.publishers[p + "robot_to_camera"] = self.nt.getStructTopic(
                    "/Spot/robot/profile/" + p + "robot_to_camera", Transform3d
                ).publish(self.options)
            pose = pose_value(camera.robot_to_camera)
            self.publishers[p + "robot_to_camera"].set(
                Transform3d(pose.translation(), pose.rotation())
            )
            for mode in camera.allowed_modes:
                for key, value in asdict(mode).items():
                    if key != "id":
                        self.put(p + "modes/" + mode.id + "/" + key, value)
            self.put(p + "modes", [m.id for m in camera.allowed_modes])
            for control in camera.controls:
                for key, value in asdict(control).items():
                    if key != "name":
                        self.put(
                            p + "controls/" + control.name + "/" + key,
                            value,
                            "Double" if key == "default_value" else None,
                        )
            self.put(p + "controls", [c.name for c in camera.controls])
        self.put("cameras", [c.name for c in profile.cameras])
        self.session.set(manifest.robot_session)
        self.header.set(manifest.manifest_hash)

    def close(self):
        self.header.close()
        self.session.close()
        for pub in self.publishers.values():
            pub.close()


class StatePublisher:
    def __init__(self, nt, options):
        from spot_vision.structs import RobotStatus

        self.publisher = nt.getStructTopic("/Spot/robot/state", RobotStatus).publish(options)

    def set(self, state):
        from spot_vision.structs import RobotStatus, tag_mask, token

        self.publisher.set(
            RobotStatus(
                *token(state.robot_session),
                state.enabled,
                state.sequence,
                state.tag_selection_generation,
                tag_mask(state.allowed_tag_ids, manifest().profile.field),
            )
        )

    def close(self):
        self.publisher.close()
