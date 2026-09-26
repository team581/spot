"""Disposable alpha daemon + LAN camera viewer launcher.

Run from the repository checkout on the Jetson.  This intentionally lives in
``tools`` and is not installed or referenced by systemd.
"""
from __future__ import annotations

import argparse
import logging

from prototype_stream import StreamHub

from buddy_vision.config import load_config
from buddy_vision.logging_utils import configure_logging
from buddy_vision.service import VisionService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    configure_logging(verbose=True, json_logs=True)
    config = load_config(args.config)
    hub = StreamHub([camera.id for camera in config.cameras if camera.enabled])
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
        service = VisionService(config, frame_observer=lambda frame: hub.publish(
            frame.camera_id, frame.image, frame.sequence))
        service.run_forever()
    finally:
        hub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
