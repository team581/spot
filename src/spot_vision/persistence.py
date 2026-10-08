"""Versioned, immutable group generations outside the installed release."""

from __future__ import annotations

import copy
import fcntl
import hashlib
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


def canonical_bytes(data: dict) -> bytes:
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
        fsync_directory(self.root)
        self._lock = threading.RLock()
        self.fault = ""
        self._history_cache = {}

    def _load_pointer(self, name: str) -> StateSnapshot:
        pointer = json.loads((self.root / name).read_bytes())
        generation = pointer["generation"]
        if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
            raise ConfigError("invalid generation identity")
        raw = (self.generations / f"{generation}.json").read_bytes()
        if len(raw) > MAX_STATE_BYTES or hashlib.sha256(raw).hexdigest() != pointer["sha256"]:
            raise ConfigError("state checksum mismatch or state too large")
        document = json.loads(raw)
        if (
            document["schema_version"] != STATE_SCHEMA
            or document["generation"] != generation
            or not isinstance(document["data"], dict)
            or document.get("data_sha256")
            != hashlib.sha256(canonical_bytes(document["data"])).hexdigest()
        ):
            raise ConfigError("unsupported or incoherent state schema")
        return StateSnapshot(generation, document["data"])

    def load(self) -> StateSnapshot:
        with self._lock:
            if not (self.root / "active.json").exists():
                return StateSnapshot("", {})
            try:
                return self._load_pointer("active.json")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.fault = f"Corrupt state: {exc}"
                try:
                    return self._load_pointer("last-known-good.json")
                except (OSError, ValueError, KeyError, TypeError):
                    return StateSnapshot("", {})

    def read_generation(self, generation: str) -> StateSnapshot:
        if not _GENERATION.fullmatch(generation):
            raise ConfigError("invalid generation identity")
        with (self.generations / f"{generation}.json").open("rb") as stream:
            raw = stream.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES:
            raise ConfigError("History generation exceeds size bound")
        document = json.loads(raw)
        if document["schema_version"] != STATE_SCHEMA or document["generation"] != generation:
            raise ConfigError("unsupported or incoherent state schema")
        if (
            document.get("data_sha256")
            != hashlib.sha256(canonical_bytes(document["data"])).hexdigest()
        ):
            raise ConfigError("history checksum mismatch")
        return StateSnapshot(generation, document["data"])

    def commit(
        self,
        data: dict,
        expected: str,
        *,
        apply: Callable[[StateSnapshot], None],
        rollback: Callable[[StateSnapshot], None],
        eligible: Callable[[], None],
    ) -> StateSnapshot:
        """Apply a whole group, then acknowledge only its durable activation.

        A complete immutable generation is staged first. Power loss before the
        active-pointer rename boots the old generation; after it boots the new
        complete group. A failed apply never changes the active pointer.
        The caller holds its configuration lock through this commit.
        """
        with self._lock, (self.root / ".commit.lock").open("a+b") as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            old = self.load()
            if expected != old.generation:
                raise ConfigError("revision conflict; fetch current configuration")
            eligible()
            generation = uuid.uuid4().hex
            snapshot = StateSnapshot(generation, copy.deepcopy(data))
            raw = canonical_bytes(
                {
                    "schema_version": STATE_SCHEMA,
                    "generation": generation,
                    "data": snapshot.data,
                    "data_sha256": hashlib.sha256(canonical_bytes(snapshot.data)).hexdigest(),
                }
            )
            if len(raw) > MAX_STATE_BYTES:
                raise ConfigError("state exceeds limit")
            durable_replace(self.generations / f"{generation}.json", raw)
            old_document = {}
            if old.generation:
                for name in ("active.json", "last-known-good.json"):
                    try:
                        candidate = json.loads((self.root / name).read_bytes())
                        if candidate.get("generation") == old.generation:
                            old_document = candidate
                            break
                    except (OSError, ValueError):
                        continue
            calibration_current = old_document.get("calibration_current", old.generation)
            calibration_previous = old_document.get("calibration_previous", [])
            if (
                data.get("calibrations", {}) != old.data.get("calibrations", {})
                or not calibration_current
            ):
                calibration_previous = list(
                    dict.fromkeys([calibration_current] + calibration_previous)
                )[:63]
                calibration_current = generation
            pointer = canonical_bytes(
                {
                    "generation": generation,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "previous": self._history_ids(old.generation)[:63],
                    "calibration_current": calibration_current,
                    "calibration_previous": [g for g in calibration_previous if g],
                }
            )
            old_pointer = None
            if old.generation:
                old_raw = (self.generations / f"{old.generation}.json").read_bytes()
                old_document.update(
                    generation=old.generation, sha256=hashlib.sha256(old_raw).hexdigest()
                )
                old_pointer = canonical_bytes(old_document)
            try:
                apply(snapshot)
                eligible()  # enabled/unknown state can change during application
                if old.generation:
                    durable_replace(self.root / "last-known-good.json", old_pointer)
                durable_replace(self.root / "active.json", pointer)
            except BaseException:
                # If rename succeeded but directory fsync failed, restore the
                # previous pointer as well as runtime; never report success.
                if old.generation:
                    durable_replace(self.root / "active.json", old_pointer)
                else:
                    (self.root / "active.json").unlink(missing_ok=True)
                    fsync_directory(self.root)
                rollback(old)
                self._prune_generations()
                raise
            self.fault = ""
            self._prune_generations()
            return snapshot

    def _history_ids(self, current: str) -> list[str]:
        if not current:
            return []
        try:
            pointer = json.loads((self.root / "active.json").read_bytes())
            previous = pointer.get("previous", [])
            if not isinstance(previous, list):
                previous = []
        except (OSError, ValueError):
            previous = []
        return list(
            dict.fromkeys(
                [current]
                + [
                    item
                    for item in previous
                    if isinstance(item, str) and _GENERATION.fullmatch(item)
                ]
            )
        )[:64]

    def _prune_generations(self) -> None:
        """Retain activated configuration/calibration histories and LKG only."""
        keep = set()
        for name in ("active.json", "last-known-good.json"):
            try:
                pointer = json.loads((self.root / name).read_bytes())
                keep.update([pointer["generation"], pointer.get("calibration_current", "")])
                keep.update(pointer.get("previous", []))
                keep.update(pointer.get("calibration_previous", []))
            except (OSError, ValueError, KeyError, TypeError):
                return  # corrupt pointer requires recovery, never speculative deletion
        try:
            for path in self.generations.glob("*.json"):
                if _GENERATION.fullmatch(path.stem) and path.stem not in keep:
                    path.unlink()
            fsync_directory(self.generations)
        except OSError:
            pass  # cleanup cannot make a durable successful apply look rejected

    def history(self) -> list[dict]:
        """Activated calibration changes survive frequent exposure/tuning writes."""
        active = self.load().generation
        try:
            pointer = json.loads((self.root / "active.json").read_bytes())
            current = pointer.get("calibration_current", active)
            generations = list(
                dict.fromkeys(
                    [current] + pointer.get("calibration_previous", self._history_ids(active)[1:])
                )
            )[:64]
        except (OSError, ValueError, TypeError):
            current, generations = active, self._history_ids(active)
        result = []
        for generation in generations:
            if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
                continue
            try:
                path = self.generations / f"{generation}.json"
                stamp = path.stat()
                signature = (stamp.st_mtime_ns, stamp.st_size)
                cached = self._history_cache.get(generation)
                if cached and cached[0] == signature:
                    cameras = copy.deepcopy(cached[1])
                else:
                    records = self.read_generation(generation).data.get("calibrations", {}).values()
                    cameras = [
                        {
                            "identity": record["identity"],
                            "mode_signature": record["mode_signature"],
                            "saved_at": record.get("saved_at"),
                            "hash": record.get("hash", ""),
                        }
                        for record in records
                    ]
                    self._history_cache[generation] = (signature, cameras)
                result.append(
                    {"generation": generation, "active": generation == current, "cameras": cameras}
                )
            except (OSError, ValueError, KeyError, TypeError):
                result.append(
                    {
                        "generation": generation,
                        "active": generation == current,
                        "error": "History generation is corrupt; restore unavailable",
                        "cameras": [],
                    }
                )
        self._history_cache = {
            key: value for key, value in self._history_cache.items() if key in generations
        }
        return result

    def export(self) -> bytes:
        snapshot = self.load()
        return canonical_bytes({"schema_version": STATE_SCHEMA, "data": snapshot.data})
