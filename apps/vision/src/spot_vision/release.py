"""Installed artifact identity, deployment history and reliable wall time."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import ConfigError


def wall_time_available() -> bool:
    # A plausible year alone does not prove an embedded RTC is synchronized.
    try:
        return Path("/run/systemd/timesync/synchronized").exists() and time.time() > 1704067200
    except OSError:
        return False


def installed_identity(*, backend: str, manifest_path: Path | None = None) -> dict:
    from . import _spot_cuda as native

    module_path = Path(native.__file__).resolve()
    sha256 = hashlib.sha256(module_path.read_bytes()).hexdigest()
    path = manifest_path or Path(__file__).parent / "build-manifest.json"
    if not path.is_file():
        raise ConfigError("Installed build manifest is missing; build and install a beta release")
    manifest = json.loads(path.read_bytes())
    if manifest.get("schema_version") != 1 or manifest.get("native_sha256") != sha256:
        raise ConfigError("Installed native module differs from the release build manifest")
    if backend == "cuda" and (
        not manifest.get("native_cuda") or not getattr(native, "CUDA_AVAILABLE", False)
    ):
        raise ConfigError("CUDA production release required; CPU fallback cannot certify beta")
    package = Path(__file__).parent.resolve()
    for relative, expected in manifest.get("artifact_hashes", {}).items():
        artifact = (package / relative).resolve()
        if (
            not artifact.is_relative_to(package)
            or not artifact.is_file()
            or hashlib.sha256(artifact.read_bytes()).hexdigest() != expected
        ):
            raise ConfigError(f"Installed application artifact differs from manifest: {relative}")
    from importlib.metadata import version

    manifest["runtime_versions"] = {
        name: version(name)
        for name in (
            "spot-vision",
            "robotpy-wpiutil",
            "pyntcore",
            "numpy",
            "opencv-contrib-python-headless",
        )
    }
    manifest["loaded_native_path"] = str(module_path)
    manifest["process_started_at"] = (
        datetime.now(timezone.utc).isoformat() if wall_time_available() else None
    )
    manifest["wall_time_available"] = wall_time_available()
    return manifest
