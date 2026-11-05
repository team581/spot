"""Print the JSON Schema for robot code's spot-config.json, published on the docs site."""

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

# Import from source so autofix can run this without building the native extension.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from spot_vision.protocol import SCHEMA_URL  # noqa: E402
from spot_vision.protocol_models import RobotConfiguration  # noqa: E402


def tidy(schema: dict) -> None:
    """Drop generated titles, which only repeat property names."""
    schema.pop("title", None)
    for field in schema.get("properties", {}).values():
        field.pop("title", None)


schema = TypeAdapter(RobotConfiguration).json_schema()
for definition in [schema, *schema["$defs"].values()]:
    tidy(definition)
schema["properties"] = {"$schema": {"type": "string"}, **schema["properties"]}
print(
    json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": SCHEMA_URL,
            **schema,
            "title": "Spot camera configuration",
            "description": "Robot code's src/main/deploy/spot-config.json. See https://spot.frc581.com/robot-config/.",
        },
        indent=2,
    )
)
