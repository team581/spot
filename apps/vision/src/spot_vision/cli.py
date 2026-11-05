from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from .config import ConfigError
from .logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spot-vision")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json-logs", action="store_true")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run the installed robot-integrated service and GUI")
    run.add_argument("--installation", default="/etc/spot-vision/installation.json")
    run.add_argument("--state-root", default="/var/lib/spot-vision")

    health = subcommands.add_parser("check-health", help="check the running service")
    health.add_argument("--url", default="http://127.0.0.1:5800")
    health.add_argument("--timeout", type=int, default=120)
    health.add_argument(
        "--robot", action="store_true", help="require robot connection and camera readiness"
    )

    regression = subcommands.add_parser(
        "image-regression", help="measure fixed-image pipeline accuracy"
    )
    regression.add_argument("--manifest", required=True)
    regression.add_argument("--backend", choices=("cpu", "cuda"), default="cpu")
    regression.add_argument("--repeats", type=int, default=5)
    regression.add_argument("--output", help="write the JSON metric report")

    return parser


def _check_health_status(status: dict, package_path: str, *, robot: bool) -> None:
    if status["software"]["package_path"] != package_path:
        raise ConfigError("Running service uses a different package")
    if not robot:
        return
    if (
        not status["fresh"]
        or status["clock"]["state"] != "Synchronized"
        or status["applied_generation"] != status["revision"]
    ):
        raise ConfigError("Robot configuration or clock synchronization pending")
    if status["lock_reason"]:
        raise ConfigError("Robot connection required for readiness check")
    required = [
        camera
        for camera in status["cameras"]
        if camera.get("required") and camera.get("health") != "Disabled"
    ]
    if not required or any(
        not camera["connected"]
        or not camera["calibrated"]
        or not camera.get("timestamp_qualified")
        or camera.get("metrics", {}).get("detect_age_s") is None
        or camera["metrics"]["detect_age_s"] > 0.5
        for camera in required
    ):
        raise ConfigError("Required camera/mode/calibration/timing readiness pending")


def _run_check_health(args) -> int:
    if not 1 <= args.timeout <= 300:
        raise ConfigError("Timeout must be 1–300 seconds")
    deadline = time.monotonic() + args.timeout
    error = "Readiness timeout"
    while time.monotonic() < deadline:
        try:
            with urlopen(args.url.rstrip("/") + "/api/status", timeout=2) as response:
                status = json.load(response)
            _check_health_status(status, str(Path(sys.prefix).resolve()), robot=args.robot)
            print(json.dumps(status["software"], indent=2))
            return 0
        except (OSError, ValueError, KeyError, TypeError, ConfigError) as exc:
            error = str(exc)
            time.sleep(0.5)
    raise ConfigError(error)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose, args.json_logs)
    try:
        if args.command == "run":
            from .app import run

            return run(args)
        if args.command == "check-health":
            return _run_check_health(args)
        if args.command == "image-regression":
            from .regression import run_image_regression

            if args.repeats < 1:
                raise ConfigError("--repeats must be positive")
            report = run_image_regression(args.manifest, backend=args.backend, repeats=args.repeats)
            serialized = json.dumps(report, indent=2, allow_nan=False)
            if args.output:
                Path(args.output).write_text(serialized + "\n")
            print(serialized)
            return 0 if report["passed"] else 1
    except (ConfigError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2
    parser.error(f"unhandled command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
