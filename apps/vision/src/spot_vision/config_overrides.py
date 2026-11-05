"""Persistent dashboard edits, keyed by camera/control names instead of list indices."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict

from . import protocol_models as data
from .protocol import restore

GROUPS = {"robot_to_camera", "allowed_modes", "calibration", "timestamp_qualification"}


def values(settings: data.RobotConfiguration) -> dict:
    document = asdict(settings)
    document["cameras"] = {camera["name"]: camera for camera in document["cameras"]}
    for camera in document["cameras"].values():
        camera["controls"] = {control["name"]: control for control in camera["controls"]}
    return document


def settings(document: dict) -> data.RobotConfiguration:
    document = copy.deepcopy(document)
    document["cameras"] = list(document["cameras"].values())
    for camera in document["cameras"]:
        camera["controls"] = [
            control for control in camera["controls"].values() if control is not None
        ]
    return restore(data.RobotConfiguration, json.dumps(document).encode())


def merge(baseline: dict, overrides: dict) -> dict:
    result = copy.deepcopy(baseline)
    for key, value in overrides.items():
        if key not in GROUPS and isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def changes(before: dict, after: dict, path: tuple[str, ...] = ()) -> dict:
    result = {}
    for key in before.keys() | after.keys():
        if key not in after:
            result[key] = None
        elif key not in before or before[key] != after[key]:
            if (
                key not in GROUPS
                and not (len(path) == 3 and path[0] == "cameras" and path[2] == "controls")
                and isinstance(before.get(key), dict)
                and isinstance(after[key], dict)
            ):
                result[key] = changes(before[key], after[key], (*path, key))
            else:
                result[key] = copy.deepcopy(after[key])
    return result


def entries(overrides: dict, prefix: str = "") -> list[dict]:
    result = []
    for key, value in overrides.items():
        path = prefix + key
        if isinstance(value, dict) and key not in GROUPS and not prefix.endswith("/controls/"):
            result.extend(entries(value, path + "/"))
        else:
            result.append({"path": path, "value": value})
    return result


def clear(overrides: dict, path: str) -> dict:
    result = copy.deepcopy(overrides)

    def remove(node, parts):
        key = parts[0]
        if len(parts) == 1:
            node.pop(key, None)
        elif isinstance(node.get(key), dict):
            remove(node[key], parts[1:])
            if not node[key]:
                del node[key]

    if path:
        remove(result, path.split("/"))
    else:
        result.clear()
    return result
