"""Packaged application entry point. UI readiness does not wait for USB or NT."""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import threading
from datetime import datetime, timezone
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

from .calibration import CalibrationManager
from .clock import wall_time_available
from .config import ConfigError, NtConfig
from .devices import _run
from .http_server import HttpServer
from .networking import NetworkClient
from .processing import ProcessingPolicy
from .runtime import Runtime


def local_addresses() -> list[str]:
    try:
        links = json.loads(_run(["ip", "-json", "address", "show"], timeout=1))
        return [
            address["local"]
            for link in links
            for address in link.get("addr_info", [])
            if address.get("family") == "inet"
        ]
    except (ConfigError, ValueError, KeyError):
        return ["127.0.0.1"]


def software_info() -> dict:
    from importlib.util import find_spec

    native_cuda = False
    if find_spec("spot_vision._spot_cuda") is not None:
        from . import _spot_cuda as native

        native_cuda = bool(native.CUDA_AVAILABLE)
    system = Path("/run/current-system")
    return {
        "package_path": str(Path(sys.prefix).resolve()),
        "system_path": str(system.resolve()) if system.exists() else None,
        "configuration_revision": os.environ.get("SPOT_CONFIGURATION_REVISION") or None,
        "version": version("spot-vision"),
        "native_cuda": native_cuda,
        "process_started_at": datetime.now(timezone.utc).isoformat()
        if wall_time_available()
        else None,
    }


def run(args) -> int:
    config = json.loads(Path(args.installation).read_bytes())
    if (
        set(config) - {"schema_version", "nt", "http", "backend", "processing"}
        or config.get("schema_version") != 2
    ):
        raise ConfigError("Invalid installation configuration")
    backend = config.get("backend", "cuda")
    if backend not in {"cpu", "cuda"}:
        raise ConfigError("Invalid detector backend")
    nt = NtConfig(**config["nt"])
    http = config.get("http", {})
    if set(http) - {"bind", "port", "hostnames"}:
        raise ConfigError("Invalid HTTP configuration")
    addresses = local_addresses()
    software = software_info()
    if backend == "cuda" and not software["native_cuda"]:
        raise ConfigError("CUDA backend requires a CUDA build")
    runtime = Runtime(
        Path(args.state_root),
        nt,
        backend=backend,
        processing=ProcessingPolicy.parse(config.get("processing")),
    )
    runtime.network = NetworkClient()
    runtime.software = software
    runtime.endpoint["local_addresses"] = addresses
    runtime.calibration = CalibrationManager(runtime)
    assets = Path(str(files("spot_vision.web")))
    for relative in (
        "index.html",
        "blazing-bulldogs.svg",
        "docs/index.html",
        "docs/pagefind/pagefind.js",
    ):
        if not (assets / relative).is_file():
            raise ConfigError(f"Installed UI asset missing: {relative}")
    server = HttpServer(
        (http.get("bind", "0.0.0.0"), int(http.get("port", 5800))),
        runtime,
        allowed_hosts=[socket.gethostname(), "spot.local", *addresses, *http.get("hostnames", [])],
    )
    web_thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    stopped = threading.Event()
    prior = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        prior[signum] = signal.signal(signum, lambda *_: stopped.set())
    try:
        runtime.start()
        runtime.network.worker.start()
        web_thread.start()
        runtime.watchdog.ready()
        while not stopped.wait(0.2):
            if not web_thread.is_alive() or not runtime.tick():
                raise RuntimeError(runtime.fatal or "HTTP service worker exited")
    finally:
        server.shutdown()
        if web_thread.is_alive():
            web_thread.join(5)
        runtime.network.close()
        runtime.close()
        for signum, handler in prior.items():
            signal.signal(signum, handler)
    return 0
