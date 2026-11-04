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


def smoke(environment: Path, work: Path, *, native_cuda: bool = False) -> None:
    from spot_vision import app, cli, runtime
    from spot_vision.devices import DeviceManager

    assert Path(sys.prefix).resolve() == environment.resolve()
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
    server_type = app.HttpServer

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
                        assert status["software"]["native_cuda"] is native_cuda
                        assert status["software"]["package_path"] == str(environment.resolve())
                        # Exercise the operator command against this real installed server.
                        assert (
                            cli.main(
                                [
                                    "check-health",
                                    "--url",
                                    f"http://127.0.0.1:{servers[0].server_port}",
                                    "--timeout",
                                    "2",
                                ]
                            )
                            == 0
                        )
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
            runtime,
            "DeviceManager",
            lambda registry: DeviceManager(registry, enumerate_fn=lambda: []),
        ),
        patch.object(app, "HttpServer", server),
    ):
        result = cli.main(
            ["run", "--installation", str(installation), "--state-root", str(work / "state")]
        )
    inspector.join(15)
    assert not inspector.is_alive(), "Installed HTTP inspection did not finish"
    if errors:
        raise errors[0]
    assert result == 0, result
    print(
        "Installed package: real startup, package path, empty discovery, HTTP chunks and offline docs verified"
    )


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] in {"--smoke", "--smoke-cuda"}:
        smoke(Path(sys.argv[2]), Path(sys.argv[3]), native_cuda=sys.argv[1] == "--smoke-cuda")
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
                "uv",
                "sync",
                "--project",
                str(root),
                "--locked",
                "--package",
                "spot-vision",
                "--no-dev",
                "--extra",
                "nt",
                "--extra",
                "systemd",
                "--no-install-workspace",
                "--python",
                sys.executable,
                "--no-python-downloads",
            ],
            check=True,
            env={**clean_env, "UV_PROJECT_ENVIRONMENT": str(environment)},
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(environment / "bin/python"),
                "--no-deps",
                str(wheel),
            ],
            check=True,
            env=clean_env,
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
