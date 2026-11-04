"""Serve the production bundle with synthetic cameras and the real HTTP boundary."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vision/tools"))
from beta_ui_fixture import FixtureRuntime

from spot_vision.beta_web import BetaHttpServer

assets = os.environ.get("SPOT_DASHBOARD_ASSETS")
server = BetaHttpServer(
    ("127.0.0.1", 5818),
    FixtureRuntime(),
    assets=Path(assets) if assets else Path(__file__).resolve().parents[3] / "dist/dashboard",
)
server.serve_forever()
