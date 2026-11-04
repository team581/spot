"""Explicit measured capture timing; absent evidence never becomes zero uncertainty."""

from __future__ import annotations

import math

from .beta_contract import content_hash
from .config import ConfigError
from .persistence import canonical_bytes


def timing_signature(mode, controls: dict) -> str:
    import hashlib

    return hashlib.sha256(content_hash(mode).encode() + canonical_bytes(controls)).hexdigest()


def validate_timing_evidence(record: dict) -> None:
    if not isinstance(record, dict) or set(record) != {
        "identity",
        "signature",
        "timestamp_source",
        "correction_us",
        "uncertainty_s",
        "measured_cycles",
        "evidence",
    }:
        raise ConfigError("Complete measured timing record required")
    if not isinstance(record["identity"], str) or not 1 <= len(record["identity"]) <= 128:
        raise ConfigError("Timing identity must be bounded text")
    signature = record["signature"]
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(c not in "0123456789abcdef" for c in signature)
    ):
        raise ConfigError("Timing signature must be a SHA-256 digest")
    if record["timestamp_source"] != "read-completion-local-nt":
        raise ConfigError("Unsupported capture timestamp source")
    correction, uncertainty, cycles = (
        record["correction_us"],
        record["uncertainty_s"],
        record["measured_cycles"],
    )
    if type(correction) is not int or not -250_000 <= correction <= 0:
        raise ConfigError("Measured capture correction must be between -250000 and 0 µs")
    if (
        type(uncertainty) not in (int, float)
        or not math.isfinite(uncertainty)
        or not 0 < uncertainty <= 0.02
    ):
        raise ConfigError("Measured timestamp uncertainty must be positive and at most 20 ms")
    if type(cycles) is not int or cycles < 100 or cycles > 10_000_000:
        raise ConfigError("At least 100 measured capture cycles required")
    if not isinstance(record["evidence"], str) or not 16 <= len(record["evidence"]) <= 2048:
        raise ConfigError("Supply capture/FPGA measurement evidence and conditions")


def validate_timing(record: dict, identity: str, mode, controls: dict) -> None:
    validate_timing_evidence(record)
    if record["identity"] != identity or record["signature"] != timing_signature(mode, controls):
        raise ConfigError(
            "Timing qualification does not match this camera, mode and control readback"
        )
