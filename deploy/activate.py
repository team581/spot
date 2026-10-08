#!/usr/bin/env python3
"""Atomic release switch with installed-process verification and automatic rollback."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path("/opt/spot-vision")
STATE = Path("/var/lib/spot-vision")


def replace_link(path, target):
    temporary = path.with_name(path.name + ".next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def record(document):
    destination = STATE / "deployments.json"
    temporary = destination.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(document, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    os.chmod(destination, 0o644)
    fd = os.open(STATE, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stamp():
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc).isoformat()
        if Path("/run/systemd/timesync/synchronized").exists()
        else None
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release_id")
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Verify installed GUI/native only; robot qualification stays pending",
    )
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error("Verification timeout must be between 1 and 300 seconds")
    if os.geteuid() != 0 or not re.fullmatch(r"[a-f0-9]{16}", args.release_id):
        parser.error("Run as root with an installed release ID")
    target = ROOT / "releases" / args.release_id
    executable = target / ".venv/bin/spot-vision"
    if not executable.is_file():
        parser.error("Release is not installed")
    identity = json.loads(
        subprocess.check_output(
            [
                "runuser",
                "-u",
                "spot-vision",
                "--",
                str(executable),
                "verify-release",
                "--backend",
                "cuda",
            ],
            timeout=args.timeout,
        )
    )
    if identity["release_id"] != args.release_id:
        parser.error("Installed manifest does not match requested release")
    installation = json.loads(Path("/etc/spot-vision/beta.json").read_bytes())
    endpoint = f"http://127.0.0.1:{installation.get('http', {}).get('port', 5800)}"
    previous = (ROOT / "current").resolve() if (ROOT / "current").exists() else None
    document = (
        json.loads((STATE / "deployments.json").read_bytes())
        if (STATE / "deployments.json").exists()
        else {}
    )
    attempt = {
        "release_id": args.release_id,
        "target": os.uname().nodename,
        "started_at": stamp(),
        "verification": "pending",
        "mode": "setup only" if args.setup_only else "robot readiness",
    }
    document["latest_attempt"] = attempt
    record(document)
    try:
        replace_link(ROOT / "current", target)
        subprocess.run(
            ["systemctl", "restart", "spot-vision.service"], check=True, timeout=args.timeout
        )
        deadline = time.monotonic() + args.timeout
        error = "Readiness timeout"
        while time.monotonic() < deadline:
            try:
                with urlopen(endpoint + "/health", timeout=2) as response:
                    status = json.load(response)
                if (
                    status["release"]["release_id"] != args.release_id
                    or status["release"]["native_sha256"] != identity["native_sha256"]
                ):
                    raise ValueError("Running Python/native identity mismatch")
                with urlopen(endpoint + "/", timeout=2) as response:
                    if b"Spot" not in response.read(1024):
                        raise ValueError("Installed GUI is unavailable")
                if not args.setup_only:
                    if (
                        not status["fresh"]
                        or status["clock"]["state"] != "Synchronized"
                        or status["applied_generation"] != status["revision"]
                    ):
                        raise ValueError("Robot profile/synchronization acknowledgement pending")
                    if status["lock_reason"]:
                        raise ValueError("Disabled robot required for deployment qualification")
                    required = [
                        c
                        for c in status["cameras"]
                        if c.get("required") and c.get("health") != "Disabled"
                    ]
                    if not required or any(
                        not c["connected"]
                        or not c["calibrated"]
                        or not c.get("timestamp_qualified")
                        or c.get("metrics", {}).get("detect_age_s") is None
                        or c["metrics"]["detect_age_s"] > 0.5
                        for c in required
                    ):
                        raise ValueError(
                            "Required camera/mode/calibration/timing readiness pending"
                        )
                attempt["verification"] = (
                    "verified setup; hardware pending"
                    if args.setup_only
                    else "verified robot readiness"
                )
                attempt["completed_at"] = stamp()
                attempt["running_release"] = args.release_id
                document["last_successful_deployment"] = attempt.copy()
                document["rollback"] = False
                record(document)
                print(json.dumps(attempt, indent=2))
                return 0
            except (OSError, ValueError, KeyError, TypeError) as exc:
                error = str(exc)
                time.sleep(0.5)
        raise RuntimeError(error)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        attempt["verification"], attempt["error"] = "failed", str(exc)
        attempt["completed_at"] = stamp()
        document["rollback"] = False
        try:
            if previous:
                replace_link(ROOT / "current", previous)
                subprocess.run(
                    ["systemctl", "restart", "spot-vision.service"],
                    check=True,
                    timeout=args.timeout,
                )
                deadline = time.monotonic() + args.timeout
                while time.monotonic() < deadline:
                    try:
                        with urlopen(endpoint + "/health", timeout=2) as response:
                            restored = json.load(response)
                        if restored["release"]["release_id"] != previous.name:
                            raise ValueError("Previous release not running")
                        with urlopen(endpoint + "/", timeout=2) as response:
                            if b"Spot" not in response.read(1024):
                                raise ValueError("Restored GUI unavailable")
                        attempt["restored_release"] = previous.name
                        attempt["rollback_verification"] = "verified restored process and GUI"
                        document["rollback"] = True
                        break
                    except (OSError, ValueError, KeyError):
                        time.sleep(0.5)
                else:
                    raise RuntimeError("Previous release restoration verification timed out")
            else:
                subprocess.run(
                    ["systemctl", "stop", "spot-vision.service"], check=False, timeout=args.timeout
                )
        except (OSError, RuntimeError, subprocess.SubprocessError) as rollback_error:
            attempt["rollback_error"] = str(rollback_error)
        record(document)
        print(json.dumps(attempt, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
