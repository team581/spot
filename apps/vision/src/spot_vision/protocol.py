"""Robot-supplied JSON camera defaults and typed field/policy topics."""

from __future__ import annotations

import json
from dataclasses import asdict
from functools import cache

from pydantic import TypeAdapter, ValidationError

from .config import ConfigError

# Published by the docs site; robot configuration files may name it as "$schema".
SCHEMA_URL = "https://spot.frc581.com/spot-config.schema.json"


def snapshot(value) -> bytes:
    return json.dumps(asdict(value), separators=(",", ":"), allow_nan=False).encode()


@cache
def _adapter(cls) -> TypeAdapter:
    return TypeAdapter(cls)


def restore(cls, payload):
    """Parse JSON into a configuration model, naming each invalid field in the error."""
    try:
        document = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid JSON: {exc}") from exc
    if isinstance(document, dict) and "$schema" in document:
        del document["$schema"]  # editor hint, not configuration
        payload = json.dumps(document)
    try:
        return _adapter(cls).validate_json(payload)
    except ValidationError as exc:
        raise ConfigError(
            "; ".join(
                ".".join(map(str, error["loc"])) + ": " + error["msg"] for error in exc.errors()
            )
        ) from exc


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
        age = v("maxAgeS", "Double", 0.0)
        future = v("futureToleranceS", "Double", 0.0)
        if not self.complete:
            raise ConfigurationIncomplete()
        if self._configuration is None or document != self._document:
            self._configuration = restore(data.RobotConfiguration, document)
            self._document = document
        settings = self._configuration
        return data.Manifest(
            data.Profile(
                cameras=settings.cameras,
                field=field,
                max_age_s=age,
                future_tolerance_s=future,
                processing=settings.processing,
            )
        )

    def close(self):
        for subscriber in self.subscribers.values():
            subscriber.close()
