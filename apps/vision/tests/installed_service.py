"""Install a wheel with production dependencies, then smoke-test its real startup."""

from __future__ import annotations

import http.client
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch


def smoke(environment: Path, work: Path) -> None:
    import spot_vision
    from spot_vision import beta_app, beta_runtime, cli
    from spot_vision.devices import DeviceManager

    assert Path(spot_vision.__file__).resolve().is_relative_to(environment.resolve())
    installation = work / "installation.json"
    installation.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "backend": "cpu",
                "nt": {"enabled": False},
                "http": {"bind": "127.0.0.1", "port": 0},
            }
        )
    )
    servers, errors = [], []
    created = threading.Event()
    server_type = beta_app.BetaHttpServer

    def server(*args, **kwargs):
        instance = server_type(*args, **kwargs)
        servers.append(instance)
        created.set()
        return instance

    def inspect():
        try:
            assert created.wait(15), "Application did not create its HTTP server"
            assets = servers[0].assets
            paths = ["/", "/health", "/docs/", "/docs/pagefind/pagefind.js"]
            paths.extend(
                "/" + p.relative_to(assets).as_posix()
                for p in (assets / "assets").iterdir()
                if p.is_file()
            )
            for path in paths:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", servers[0].server_port, timeout=10
                )
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    assert response.status == 200, (path, response.status)
                    data = response.read()
                    assert data, path
                    if path == "/health":
                        status = json.loads(data)
                        assert status["cameras"] == []
                        assert status["release"]["native_cuda"] is False
                finally:
                    connection.close()
        except BaseException as error:
            errors.append(error)
        finally:
            if servers:
                os.kill(os.getpid(), signal.SIGTERM)

    inspector = threading.Thread(target=inspect, daemon=True)
    inspector.start()
    # Inject empty discovery so verification cannot acquire a developer's cameras.
    with (
        patch.object(
            beta_runtime,
            "DeviceManager",
            lambda registry: DeviceManager(registry, enumerate_fn=lambda: []),
        ),
        patch.object(beta_app, "BetaHttpServer", server),
    ):
        result = cli.main(
            ["beta", "--installation", str(installation), "--state-root", str(work / "state")]
        )
    inspector.join(15)
    assert not inspector.is_alive(), "Installed HTTP inspection did not finish"
    if errors:
        raise errors[0]
    assert result == 0, result
    print(
        "Installed wheel: real startup, artifact identity, empty discovery, HTTP chunks and offline docs verified"
    )


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--smoke":
        smoke(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    wheel = Path(sys.argv[1]).resolve()
    if wheel.is_dir():
        wheel = max(wheel.glob("spot_vision-*.whl"), key=lambda path: path.stat().st_mtime_ns)
    root = Path(__file__).resolve().parents[3]
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    with tempfile.TemporaryDirectory(prefix="spot-installed-") as temporary:
        work = Path(temporary)
        environment = work / ".venv"
        subprocess.run(
            [
                str(root / "apps/vision/deploy/install-wheel.sh"),
                str(root),
                str(wheel),
                str(environment),
            ],
            check=True,
            env={**clean_env, "SPOT_PYTHON": sys.executable},
        )
        subprocess.run(
            [
                str(environment / "bin/python"),
                str(Path(__file__).resolve()),
                "--smoke",
                str(environment),
                str(work),
            ],
            cwd=work,
            check=True,
            timeout=45,
            env=clean_env,
        )


if __name__ == "__main__":
    main()
