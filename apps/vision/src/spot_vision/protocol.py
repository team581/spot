"""Robot-supplied JSON camera defaults and typed field/policy topics."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from types import UnionType
from typing import get_args, get_origin, get_type_hints


def snapshot(value) -> bytes:
    return json.dumps(asdict(value), separators=(",", ":"), allow_nan=False).encode()


def restore(cls, payload):
    def convert(kind, value):
        if get_origin(kind) is list:
            if not isinstance(value, list):
                raise ValueError("array required")
            return [convert(get_args(kind)[0], item) for item in value]
        if get_origin(kind) is UnionType:
            return None if value is None else convert(get_args(kind)[0], value)
        if kind is dict:
            if not isinstance(value, dict):
                raise ValueError("object required")
            return value
        if is_dataclass(kind):
            hints = get_type_hints(kind)
            if not isinstance(value, dict) or set(value) != set(hints):
                raise ValueError("unknown or missing configuration fields")
            return kind(**{name: convert(member, value[name]) for name, member in hints.items()})
        if kind is float and type(value) in (int, float):
            return float(value)
        if type(value) is not kind:
            raise ValueError("invalid configuration value type")
        return value

    try:
        return convert(cls, json.loads(payload, parse_constant=lambda _: None))
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("invalid configuration snapshot") from exc


class ConfigurationIncomplete(Exception):
    """The first values have not arrived for all configured settings yet."""


class ProfileSubscriber:
    def __init__(self, instance):
        self.instance = instance
        self.subscribers = {}
        self.complete = False
        self._document = None
        self._configuration = None

    def value(self, path, kind, default):
        if path not in self.subscribers:
            topic = getattr(self.instance, "get" + kind + "Topic")("/Spot/Config/" + path)
            self.subscribers[path] = topic.subscribe(default)
        value = self.subscribers[path].getAtomic()
        self.complete = self.complete and value.time > 1
        return value.value

    def read(self):
        from . import protocol_models as data
        from .structs import FieldTag, pose_model

        self.complete = True
        v = self.value
        document = v("cameraConfig", "String", "")
        if "Field/tags" not in self.subscribers:
            self.subscribers["Field/tags"] = self.instance.getStructArrayTopic(
                "/Spot/Config/Field/tags", FieldTag
            ).subscribe([])
        tags = self.subscribers["Field/tags"].getAtomic()
        self.complete = self.complete and tags.time > 1
        field = data.FieldLayout(
            v("Field/origin", "String", ""),
            v("Field/lengthM", "Double", 0.0),
            v("Field/widthM", "Double", 0.0),
            [data.FieldTag(t.id, pose_model(t.pose), t.size) for t in tags.value],
        )
        fusion = v("fusionEnabled", "Boolean", False)
        heading = v("headingEnabled", "Boolean", False)
        age = v("maxAgeS", "Double", 0.0)
        future = v("futureToleranceS", "Double", 0.0)
        reorder = v("reorderWindowS", "Double", 0.0)
        if not self.complete:
            raise ConfigurationIncomplete()
        if self._configuration is None or document != self._document:
            self._configuration = restore(data.RobotConfiguration, document)
            self._document = document
        settings = self._configuration
        return data.Manifest(
            data.Profile(
                settings.cameras,
                field,
                fusion,
                heading,
                age,
                future,
                reorder,
                settings.processing,
            )
        )

    def close(self):
        for subscriber in self.subscribers.values():
            subscriber.close()
