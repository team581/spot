from dataclasses import replace
from pathlib import Path

from robot_fixtures import manifest
from spot_vision import protocol_models as wire
from spot_vision.contract import validate_manifest
from spot_vision.protocol import restore

STARTER = Path(__file__).resolve().parents[2] / "docs/public/starter/spot-config.json"


def test_docs_starter_config_is_accepted_by_spot():
    settings = restore(wire.RobotConfiguration, STARTER.read_bytes())
    base = manifest()
    validate_manifest(
        replace(
            base,
            profile=replace(base.profile, cameras=settings.cameras, processing=settings.processing),
        )
    )
