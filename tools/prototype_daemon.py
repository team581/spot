"""Disposable alpha daemon with calibration GUI and LAN camera viewer.

Run from the repository checkout on the Jetson.  This intentionally lives in
``tools`` and is not installed or referenced by systemd.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from alpha_calibration import AlphaCalibration
from prototype_stream import StreamHub

from spot_vision.config import load_config
from spot_vision.logging_utils import configure_logging
from spot_vision.service import VisionService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    configure_logging(verbose=True, json_logs=True)
    config = load_config(args.config)
    hub = StreamHub([camera.id for camera in config.cameras if camera.enabled])
    calibration = AlphaCalibration(
        config, hub.latest_frame, Path(args.config).resolve().parent / ".calibration-sessions",
        Path(__file__).with_name("calibration_ui.html"))
    hub.attach_calibration(calibration)
    try:
        try:
            hub.serve(args.host, args.port)
            logging.getLogger(__name__).info(
                "prototype viewer listening on %s:%d", args.host, args.port,
                extra={"prototype": {"type": "viewer", "ready": True, "port": args.port}},
            )
        except OSError as exc:
            logging.getLogger(__name__).error(
                "prototype viewer unavailable: %s", exc,
                extra={"prototype": {
                    "type": "viewer", "ready": False, "port": args.port, "error": str(exc),
                }},
            )
        service = VisionService(config, result_observer=hub.publish_result)
        hub.attach_service(service)
        service.run_forever()
    finally:
        calibration.close()
        hub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
