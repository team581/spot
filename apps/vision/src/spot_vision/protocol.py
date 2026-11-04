"""Robot configuration over native NetworkTables values.

Snapshots are JSON on Jetson storage only. Robot configuration and state are
exchanged as typed NT values and WPILib structs, never as JSON payloads.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import asdict, fields, is_dataclass
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from . import protocol_models as data


def content_bytes(value, kind=None) -> bytes:
    if isinstance(value, data.Pose):
        # WPILib normalizes quaternions when decoding its geometry structs.
        return struct.pack(
            "<7d",
            value.x_m,
            value.y_m,
            value.z_m,
            *(
                round(q * 1e12) / 1e12 if math.isfinite(q) else q
                for q in (value.qw, value.qx, value.qy, value.qz)
            ),
        )
    if is_dataclass(value):
        return b"".join(content_bytes(getattr(value, f.name), f.type) for f in fields(value))
    if isinstance(value, (list, tuple)):
        return struct.pack("<I", len(value)) + b"".join(
            content_bytes(v, get_args(kind)[0] if get_args(kind) else None) for v in value
        )
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return struct.pack("<I", len(encoded)) + encoded
    if isinstance(value, bool):
        return struct.pack("<?", value)
    if kind is float:
        return struct.pack("<d", value)
    if isinstance(value, int):
        return struct.pack("<q", value)
    return struct.pack("<d", value)


def content_hash(value) -> str:
    return hashlib.sha256(content_bytes(value)).hexdigest()


def snapshot(value) -> bytes:
    return json.dumps(asdict(value), separators=(",", ":"), allow_nan=False).encode()


def restore(cls, payload):
    def convert(kind, value):
        if get_origin(kind) is list:
            return [convert(get_args(kind)[0], item) for item in value]
        if get_origin(kind) is UnionType:
            return None if value is None else convert(get_args(kind)[0], value)
        if is_dataclass(kind):
            hints = get_type_hints(kind)
            if not isinstance(value, dict) or set(value) - set(hints):
                raise ValueError("invalid snapshot fields")
            return kind(**{name: convert(hints[name], item) for name, item in value.items()})
        if kind is float and type(value) in (int, float):
            return float(value)
        if type(value) is not kind:
            raise ValueError("invalid snapshot value type")
        return value

    try:
        return convert(cls, json.loads(payload))
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("invalid profile snapshot") from exc


class ProfileSubscriber:
    def __init__(self, instance, root):
        self.instance, self.root = instance, root + "/robot/profile/"
        self.subscribers = {}

    def value(self, name, kind, default):
        if name not in self.subscribers:
            topic = getattr(self.instance, "get" + kind + "Topic")(self.root + name)
            self.subscribers[name] = topic.subscribe(default)
        return self.subscribers[name].get()

    def read(self):
        v = self.value
        cameras = []
        for name in v("cameras", "StringArray", []):
            p = "cameras/" + name + "/"
            modes = []
            for mode in v(p + "modes", "StringArray", []):
                m = p + "modes/" + mode + "/"
                modes.append(
                    data.OpticalMode(
                        mode,
                        v(m + "width", "Integer", 0),
                        v(m + "height", "Integer", 0),
                        v(m + "pixel_format", "String", ""),
                        v(m + "fps", "Integer", 0),
                        v(m + "optical_signature", "String", ""),
                    )
                )
            controls = []
            for control in v(p + "controls", "StringArray", []):
                c = p + "controls/" + control + "/"
                controls.append(
                    data.ControlPolicy(
                        control,
                        v(c + "default_value", "Double", 0.0),
                        v(c + "allow_override", "Boolean", False),
                        v(c + "required", "Boolean", False),
                    )
                )
            cameras.append(
                data.CameraDefinition(
                    name,
                    v(p + "required", "Boolean", False),
                    v(p + "enabled", "Boolean", False),
                    self.pose(p + "robot_to_camera"),
                    v(p + "image_rotation_deg", "Integer", 0),
                    modes,
                    controls,
                    v(p + "moving_mount", "Boolean", False),
                    v(p + "joint_name", "String", ""),
                )
            )
        from .structs import FieldTag, pose_model

        key = "field/tags"
        if key not in self.subscribers:
            self.subscribers[key] = self.instance.getStructArrayTopic(
                self.root + key, FieldTag
            ).subscribe([])
        field = data.FieldLayout(
            v("field/origin", "String", ""),
            v("field/length_m", "Double", 0.0),
            v("field/width_m", "Double", 0.0),
            [data.FieldTag(t.id, pose_model(t.pose), t.size) for t in self.subscribers[key].get()],
        )
        return data.Profile(
            v("robot_id", "String", ""),
            cameras,
            field,
            v("fusion_enabled", "Boolean", False),
            v("heading_enabled", "Boolean", False),
            v("revised_trust_enabled", "Boolean", False),
            v("max_age_s", "Double", 0.0),
            v("future_tolerance_s", "Double", 0.0),
            v("reorder_window_s", "Double", 0.0),
        )

    def pose(self, key):
        from wpimath.geometry import Transform3d

        from .structs import pose_model

        if key not in self.subscribers:
            self.subscribers[key] = self.instance.getStructTopic(
                self.root + key, Transform3d
            ).subscribe(Transform3d())
        return pose_model(self.subscribers[key].get())

    def close(self):
        for sub in self.subscribers.values():
            sub.close()
