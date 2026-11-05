"""Print the HTTP API's OpenAPI document for dashboard type generation."""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

# Import from source so autofix can run this without building the native extension.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from spot_vision.http_server import create_app  # noqa: E402

app = create_app(SimpleNamespace(), assets=Path(tempfile.gettempdir()))
print(json.dumps(app.openapi(), indent=2))
