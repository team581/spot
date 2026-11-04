#!/usr/bin/env python3
"""Run on the Jetson: bounded local status collection, optionally with tegrastats.

This does not change camera settings, restart services, or create a capture owner.
"""

import argparse
import json
import math
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--interval-s", type=float, default=1)
    parser.add_argument("--port", type=int, default=5800)
    parser.add_argument("--tegrastats", action="store_true")
    args = parser.parse_args()
    if (
        not math.isfinite(args.duration_s)
        or args.duration_s <= 0
        or not math.isfinite(args.interval_s)
        or args.interval_s < 0.2
        or not 1 <= args.port <= 65535
    ):
        parser.error("Use finite positive duration, interval >=0.2 s and a valid HTTP port")
    args.output.mkdir(parents=True, exist_ok=False)
    process = None
    started = time.monotonic()
    with (
        (args.output / "status.jsonl").open("w") as status,
        (args.output / "tegrastats.txt").open("w") as thermal,
    ):
        try:
            if args.tegrastats:
                executable = shutil.which("tegrastats")
                if not executable:
                    parser.error("tegrastats is not installed; omit --tegrastats or correct PATH")
                process = subprocess.Popen(
                    [executable, "--interval", "1000"], stdout=thermal, stderr=subprocess.STDOUT
                )
            while time.monotonic() - started < args.duration_s:
                tick = time.monotonic()
                event = {
                    "elapsed_s": tick - started,
                    "monotonic_s": tick,
                    "wall_time_s": time.time(),
                }
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{args.port}/api/status", timeout=2
                    ) as response:
                        event["status"] = json.load(response)
                except Exception as error:
                    event["error"] = str(error)
                status.write(json.dumps(event, allow_nan=False) + "\n")
                status.flush()
                time.sleep(
                    max(
                        0,
                        min(
                            args.interval_s - (time.monotonic() - tick),
                            args.duration_s - (time.monotonic() - started),
                        ),
                    )
                )
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    (args.output / "capture.json").write_text(
        json.dumps(
            {
                "duration_s": time.monotonic() - started,
                "requested_duration_s": args.duration_s,
                "interval_s": args.interval_s,
                "tegrastats_returncode": process.returncode if process else None,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
