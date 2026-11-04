"""Create immutable identity for the module actually built by CMake."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def generate(root: Path, native: Path, cuda: bool, web_assets: Path) -> dict:
    def git(*arguments):
        result = subprocess.run(
            ["git", "-C", str(root), *arguments], capture_output=True, check=False
        )
        if result.returncode:
            raise RuntimeError("Release identity requires a Git checkout")
        return result.stdout

    commit = git("rev-parse", "HEAD").decode().strip()
    paths = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
    digest = hashlib.sha256()
    production = (
        "src/",
        "cpp/",
        "proto/",
        "deploy/",
        "tools/build_manifest.py",
        "docs-site/",
    )
    for relative in sorted(set(paths)):
        name = relative.decode()
        if not (name.startswith(production) or name in {"CMakeLists.txt", "pyproject.toml"}):
            continue
        path = root / name
        if path.is_file():
            digest.update(relative + b"\0" + hashlib.sha256(path.read_bytes()).digest())
        else:
            digest.update(relative + b"\0DELETED")
    version = re.search(
        r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.MULTILINE
    )[1]
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", datetime.now(timezone.utc).timestamp()))
    try:
        from google.protobuf import __version__ as protobuf_version
    except ImportError:
        protobuf_version = "build environment unavailable; generated v2 6.33.2 / v1 7.35.1"
    document = {
        "schema_version": 1,
        "source_commit": commit,
        "source_tree_sha256": digest.hexdigest(),
        "source_dirty": bool(git("status", "--porcelain")),
        "application_version": version,
        "protobuf_version": protobuf_version,
        "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "native_filename": native.name,
        "native_cuda": cuda,
        "built_at": datetime.fromtimestamp(epoch, timezone.utc).isoformat(),
    }
    document["artifact_hashes"] = {
        str(path.relative_to(root / "src/spot_vision")): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted((root / "src/spot_vision").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix == ".py"
    }
    document["artifact_hashes"].update(
        {
            "web/" + path.relative_to(web_assets).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(web_assets.rglob("*"))
            if path.is_file()
        }
    )
    document["protobuf_generated_versions"] = {"v1": "7.35.1", "v2": "6.33.2"}
    document["release_id"] = hashlib.sha256(
        json.dumps(document, sort_keys=True).encode()
    ).hexdigest()[:16]
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--cuda", choices=["ON", "OFF"], required=True)
    parser.add_argument("--web-assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(generate(args.root, args.native, args.cuda == "ON", args.web_assets), indent=2)
        + "\n"
    )
