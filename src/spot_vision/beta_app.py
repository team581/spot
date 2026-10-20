"""Packaged application entry point. UI readiness does not wait for USB or NT."""

from __future__ import annotations

import json
import signal
import socket
import threading
from pathlib import Path

from .beta_calibration import BetaCalibration
from .beta_processing import ProcessingPolicy
from .beta_runtime import BetaRuntime
from .beta_web import BetaHttpServer
from .config import ConfigError, NtConfig
from .devices import _run
from .networking import NetworkClient
from .release import installed_identity


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


def run_beta(args) -> int:
    config = json.loads(Path(args.installation).read_bytes())
    if (
        set(config) - {"schema_version", "nt", "http", "backend", "processing"}
        or config.get("schema_version") != 2
    ):
        raise ConfigError("Invalid beta installation configuration")
    backend = config.get("backend", "cuda")
    if backend not in {"cpu", "cuda"}:
        raise ConfigError("Invalid detector backend")
    nt = NtConfig(**config["nt"])
    http = config.get("http", {})
    if set(http) - {"bind", "port", "hostnames"}:
        raise ConfigError("Invalid HTTP configuration")
    addresses = local_addresses()
    release = installed_identity(backend=backend)
    runtime = BetaRuntime(
        Path(args.state_root),
        nt,
        backend=backend,
        processing=ProcessingPolicy.parse(config.get("processing")),
    )
    runtime.network = NetworkClient()
    runtime.release = release
    runtime.endpoint = {
        "configured": nt.server,
        "team": nt.team,
        "mode": "NT4 client",
        "local_addresses": addresses,
    }
    deployment_path = Path(args.state_root) / "deployments.json"
    if deployment_path.is_file():
        try:
            runtime.release["deployment"] = json.loads(deployment_path.read_bytes())
        except (OSError, ValueError):
            runtime.release["deployment_fault"] = "Deployment record is unreadable"
    runtime.calibration = BetaCalibration(runtime)
    assets = Path(__file__).parent / "web"
    for relative in (
        "index.html",
        "app.js",
        "app.css",
        "source-sans-pro.woff2",
        "blazing-bulldogs.svg",
        "docs/index.html",
        "docs/pagefind/pagefind.js",
    ):
        if not (assets / relative).is_file():
            raise ConfigError(f"Installed UI asset missing: {relative}")
    server = BetaHttpServer(
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
            if deployment_path.is_file():
                try:
                    runtime.release["deployment"] = json.loads(deployment_path.read_bytes())
                except (OSError, ValueError):
                    runtime.release["deployment_fault"] = "Deployment record is unreadable"
            if not web_thread.is_alive() or not runtime.tick():
                raise RuntimeError(runtime.fatal or "HTTP service worker exited")
    finally:
        server.shutdown()
        server.server_close()
        runtime.network.close()
        runtime.close()
        for signum, handler in prior.items():
            signal.signal(signum, handler)
    return 0
