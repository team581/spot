"""Installed HTTP boundary. Handlers enqueue configuration and read snapshots only."""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import threading
import time
from concurrent.futures import Future
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .config import ConfigError

MAX_BODY = 64 * 1024
OPERATIONS = {
    "standalone": set(),
    "debug": {"seconds", "revision"},
    "import": {"document", "revision"},
    "qualify-timing": {"record", "revision"},
    "rename": {"identity", "name", "revision"},
    "tune": {"name", "values", "revision", "reset"},
    "mode": {"name", "mode_id", "revision"},
    "replace": {"name", "identity", "revision"},
    "restore": {"generation", "identities", "calibration_hashes", "revision"},
    "calibration/board": {"board", "options", "revision"},
    "calibration/select": {"identities", "revision"},
    "calibration/reset": {"revision"},
    "calibration/pause-all": {"revision"},
    "calibration/start-all": {"revision", "phase"},
    "calibration/apply": {"identities", "revision"},
    **{
        f"calibration/{action}": {"identity", "revision", "phase", "automatic"}
        for action in ("start", "pause", "capture", "compute", "validate")
    },
}
REQUIRED = {
    "debug": {"seconds", "revision"},
    "import": {"document", "revision"},
    "qualify-timing": {"record", "revision"},
    "rename": {"identity", "name", "revision"},
    "tune": {"name", "revision"},
    "mode": {"name", "mode_id", "revision"},
    "replace": {"name", "revision"},
    "restore": {"generation", "revision"},
    "calibration/board": {"board", "options", "revision"},
    "calibration/select": {"identities", "revision"},
    "calibration/apply": {"identities", "revision"},
    **{
        f"calibration/{action}": {"identity", "revision"}
        for action in ("start", "pause", "capture", "compute", "validate")
    },
}


def validate_request(operation: str, payload: dict) -> None:
    if operation not in OPERATIONS or not isinstance(payload, dict):
        raise ConfigError("Unknown operation or invalid request")
    if set(payload) - OPERATIONS[operation] or REQUIRED.get(operation, set()) - set(payload):
        raise ConfigError("Unknown or missing request fields")
    for key, value in payload.items():
        if key in {"identity", "name", "revision", "generation", "mode_id", "phase"}:
            if not isinstance(value, str) or len(value) > 128 or any(ord(c) < 32 for c in value):
                raise ConfigError(f"{key}: bounded text required")
        elif key in {"reset", "automatic"} and type(value) is not bool:
            raise ConfigError(f"{key}: boolean required")
        elif key in {"board", "options", "values", "record", "document"} and not isinstance(
            value, dict
        ):
            raise ConfigError(f"{key}: object required")
        elif key in {"identities", "calibration_hashes"} and (
            not isinstance(value, list)
            or len(value) > 32
            or any(not isinstance(v, str) or len(v) > 128 for v in value)
        ):
            raise ConfigError("identities: bounded text list required")


class BrowserSession:
    def __init__(self) -> None:
        self.id, self.csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        self.touched = time.monotonic()
        self.tokens, self.updated = 2.0, time.monotonic()
        self.previews = {}
        self.requests = {}


class BetaHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, runtime, *, assets: Path | None = None, allowed_hosts=()):
        self.runtime = runtime
        self.assets = (assets or Path(__file__).parent / "web").resolve()
        self.sessions, self.jobs = {}, {}
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(16)
        self.allowed_hosts = {"localhost", "127.0.0.1", "::1", *allowed_hosts}
        if address[0] not in {"", "0.0.0.0", "::"}:
            self.allowed_hosts.add(address[0])
        super().__init__(address, Handler)
        self.ready = True

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def session(self, cookie: str, *, create=False) -> BrowserSession | None:
        try:
            parsed = SimpleCookie(cookie)
            identity = parsed["spot_session"].value if "spot_session" in parsed else ""
        except Exception:  # noqa: BLE001 - untrusted cookie parser boundary
            identity = ""
        now = time.monotonic()
        with self._lock:
            self.sessions = {
                key: s for key, s in self.sessions.items() if now - s.touched < 8 * 3600
            }
            session = self.sessions.get(identity)
            if session:
                session.touched = now
            elif create and len(self.sessions) < 8:
                session = BrowserSession()
                self.sessions[session.id] = session
            return session

    def enqueue(
        self, session: BrowserSession, operation: str, payload: dict, request_id: str
    ) -> str:
        with self._lock:
            if request_id in session.requests:
                return session.requests[request_id]
            now = time.monotonic()
            session.tokens = min(2.0, session.tokens + (now - session.updated) * 5)
            session.updated = now
            if session.tokens < 1:
                raise ConfigError("Request rate exceeded; wait for the pending value")
            session.tokens -= 1
            self.jobs = {
                key: job
                for key, job in self.jobs.items()
                if now - job[2] < 120 or not job[1].done()
            }
            if len(self.jobs) >= 64:
                raise ConfigError("Pending job limit reached")
            future = self.runtime.submit(operation, payload)
            job_id = secrets.token_urlsafe(16)
            self.jobs[job_id] = (session.id, future, now)
            session.requests[request_id] = job_id
            while len(session.requests) > 64:
                session.requests.pop(next(iter(session.requests)))
            return job_id


class Handler(BaseHTTPRequestHandler):
    server_version = "SpotBeta"
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args) -> None:
        pass  # Per-frame browser polling is deliberately absent from default logs.

    def _host(self) -> str:
        host = self.headers.get("Host", "")
        parsed = urlsplit("http://" + host)
        if (
            parsed.hostname not in self.server.allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or (parsed.port or 80) != self.server.server_port
        ):
            raise PermissionError("Host is not an installed Spot address")
        return host

    def _reply(self, status: int, payload, *, mime="application/json", cookie=None) -> None:
        if mime == "application/json" and not isinstance(payload, bytes):
            payload = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store" if mime == "application/json" else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; font-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        if cookie:
            self.send_header(
                "Set-Cookie",
                f"spot_session={cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800",
            )
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        try:
            self._host()
            path = unquote(urlsplit(self.path).path)
            if path == "/api/session":
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    raise PermissionError("Same-origin browser session required")
                session = self.server.session(self.headers.get("Cookie", ""), create=True)
                if session is None:
                    self._reply(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Browser session limit reached"}
                    )
                else:
                    self._reply(
                        200, {"csrf": session.csrf, "client": session.id}, cookie=session.id
                    )
                return
            if path in {"/api/status", "/health"}:
                status = self.server.runtime.status()
                self._reply(200, status)
                return
            session = self.server.session(self.headers.get("Cookie", ""))
            if path in {"/api/export", "/api/support"}:
                if not session:
                    raise PermissionError("Browser session required")
                snapshot = json.loads(self.server.runtime.store.export())
                if path == "/api/export":
                    self._reply(200, snapshot)
                else:
                    self._reply(
                        200,
                        {
                            "schema_version": 2,
                            "status": self.server.runtime.status(),
                            "configuration": snapshot,
                            "debug": self.server.runtime.debug,
                        },
                    )
                return
            if path.startswith("/api/jobs/"):
                with self.server._lock:
                    job = self.server.jobs.get(path.removeprefix("/api/jobs/"))
                if not session or not job or job[0] != session.id:
                    self._reply(404, {"error": "Job unavailable"})
                    return
                future: Future = job[1]
                if not future.done():
                    self._reply(200, {"state": "pending"})
                    return
                try:
                    self._reply(200, {"state": "applied", **future.result()})
                except Exception as exc:  # noqa: BLE001 - structured configuration rejection
                    self._reply(200, {"state": "rejected", "error": str(exc)})
                return
            if path.startswith("/api/frame/"):
                if not session:
                    raise PermissionError("Browser session required")
                identity = path.removeprefix("/api/frame/")
                if not re.fullmatch(r"[a-f0-9]{64}", identity):
                    raise ConfigError("Invalid physical camera identity")
                now = time.monotonic()
                with self.server._lock:
                    if now - session.previews.get(identity, 0) < 0.1:
                        self._reply(429, {"error": "Preview rate exceeded"})
                        return
                    session.previews[identity] = now
                self._reply(
                    200, self.server.runtime.frames.preview(identity, session.id + ":" + identity)
                )
                return
            if path.startswith("/api/"):
                self._reply(404, {"error": "Unknown endpoint"})
                return
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            asset = (self.server.assets / relative).resolve()
            if (
                not asset.is_relative_to(self.server.assets)
                or not asset.is_file()
                or asset.stat().st_size > 4 * 1024 * 1024
            ):
                self._reply(404, {"error": "Asset unavailable"})
                return
            self._reply(
                200,
                asset.read_bytes(),
                mime=mimetypes.guess_type(asset.name)[0] or "application/octet-stream",
            )
        except (ConfigError, ValueError) as exc:
            self._reply(400, {"error": str(exc)})
        except PermissionError as exc:
            self._reply(403, {"error": str(exc)})
        except (BrokenPipeError, ConnectionError, TimeoutError):
            self.close_connection = True

    def do_POST(self) -> None:
        try:
            host = self._host()
            if urlsplit(self.path).path != "/api/operations":
                raise ConfigError("Unknown mutation endpoint")
            if self.headers.get("Origin") != "http://" + host:
                raise PermissionError("Same-origin request required")
            session = self.server.session(self.headers.get("Cookie", ""))
            if session is None or not secrets.compare_digest(
                self.headers.get("X-Spot-CSRF", ""), session.csrf
            ):
                raise PermissionError("Session/CSRF check failed")
            if (
                self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json"
            ):
                raise ConfigError("Bounded JSON body required")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2 * 1024 * 1024:
                raise ConfigError("Request body size exceeded")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ConfigError("Incomplete request")

            def reject_constant(value):
                raise ConfigError(f"Invalid JSON numeric constant {value}")

            document = json.loads(raw, parse_constant=reject_constant)
            if not isinstance(document, dict) or set(document) != {
                "operation",
                "payload",
                "request_id",
            }:
                raise ConfigError("Structured operation, payload and request_id required")
            operation, payload, request_id = (
                document["operation"],
                document["payload"],
                document["request_id"],
            )
            if (
                not isinstance(operation, str)
                or not isinstance(request_id, str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", request_id)
            ):
                raise ConfigError("Invalid operation/request identity")
            if length > MAX_BODY and operation != "import":
                raise ConfigError("Request body size exceeded")
            validate_request(operation, payload)
            job_id = self.server.enqueue(session, operation, payload, request_id)
            self._reply(202, {"job_id": job_id, "state": "pending"})
        except (ConfigError, ValueError, TypeError) as exc:
            self.close_connection = True  # reject unread/oversized body safely
            self._reply(400, {"error": str(exc)})
        except PermissionError as exc:
            self.close_connection = True
            self._reply(403, {"error": str(exc)})
        except (BrokenPipeError, ConnectionError, TimeoutError):
            self.close_connection = True
