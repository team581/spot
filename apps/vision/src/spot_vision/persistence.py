"""Atomic local settings with a bounded history of calibration results."""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError

STATE_SCHEMA = 1
MAX_STATE_BYTES = 16 * 1024 * 1024
_GENERATION = re.compile(r"[a-f0-9]{32}\Z")


def canonical_bytes(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def durable_replace(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class StateSnapshot:
    generation: str
    data: dict


class StateStore:
    def __init__(self, root: Path | str = "/var/lib/spot-vision") -> None:
        self.root = Path(root)
        self.generations = self.root / "generations"
        self.generations.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.fault = ""
        self.path = self.root / "state.json"

    @staticmethod
    def _read(path: Path) -> StateSnapshot:
        raw = path.read_bytes()
        if len(raw) > MAX_STATE_BYTES:
            raise ConfigError("State exceeds limit")
        document = json.loads(raw)
        if (
            document["schema_version"] != STATE_SCHEMA
            or not _GENERATION.fullmatch(document["generation"])
            or not isinstance(document["data"], dict)
        ):
            raise ConfigError("Invalid saved state")
        return StateSnapshot(document["generation"], document["data"])

    def load(self) -> StateSnapshot:
        return self._read(self.path) if self.path.exists() else StateSnapshot("", {})

    def read_generation(self, generation: str) -> StateSnapshot:
        if not _GENERATION.fullmatch(generation):
            raise ConfigError("Invalid history entry")
        return self._read(self.generations / f"{generation}.json")

    def commit(
        self,
        data: dict,
        expected: str,
        *,
        apply: Callable[[StateSnapshot], None],
        rollback: Callable[[StateSnapshot], None],
        eligible: Callable[[], None],
    ) -> StateSnapshot:
        with self._lock:
            old = self.load()
            if expected != old.generation:
                raise ConfigError("Revision conflict; fetch current configuration")
            eligible()
            candidate = StateSnapshot(uuid.uuid4().hex, copy.deepcopy(data))
            raw = canonical_bytes(
                {
                    "schema_version": STATE_SCHEMA,
                    "generation": candidate.generation,
                    "data": candidate.data,
                }
            )
            if len(raw) > MAX_STATE_BYTES:
                raise ConfigError("State exceeds limit")
            try:
                apply(candidate)
                eligible()
                durable_replace(self.path, raw)
            except Exception:
                rollback(old)
                raise
            try:
                if data.get("calibrations", {}) != old.data.get("calibrations", {}):
                    durable_replace(self.generations / f"{candidate.generation}.json", raw)
                    for path in sorted(
                        self.generations.glob("*.json"),
                        key=lambda p: p.stat().st_mtime_ns,
                        reverse=True,
                    )[64:]:
                        path.unlink()
                self.fault = ""
            except OSError as exc:
                self.fault = f"Settings saved; calibration history unavailable: {exc}"
            return candidate

    def history(self) -> list[dict]:
        result = []
        current = self.load().data.get("calibrations", {})
        for path in sorted(
            self.generations.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True
        )[:64]:
            saved = self._read(path)
            records = saved.data.get("calibrations", {})
            result.append(
                {
                    "generation": saved.generation,
                    "active": records == current,
                    "cameras": [
                        {
                            "identity": r["identity"],
                            "mode_signature": r["mode_signature"],
                            "saved_at": r.get("saved_at"),
                            "id": r["id"],
                        }
                        for r in records.values()
                    ],
                }
            )
        return result

    def export(self) -> bytes:
        return canonical_bytes({"schema_version": STATE_SCHEMA, "data": self.load().data})
