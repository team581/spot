"""Installed HTTP boundary. Handlers enqueue configuration and read snapshots only."""

import json
import secrets
import socket
import threading
import time
from concurrent.futures import Future
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlsplit

import uvicorn
from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    create_model,
    model_validator,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import ConfigError
from .protocol_models import RobotConfiguration

MAX_BODY = 256 * 1024
MAX_IMPORT_BODY = 2 * 1024 * 1024
COOKIE = "spot_session"
CSP = (
    "default-src 'self'; img-src 'self' data:; font-src 'self'; style-src 'self'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)
# Static Starlight pages use inline theme scripts/styles and Pagefind WebAssembly.
DOCS_CSP = (
    "default-src 'self'; img-src 'self' data:; font-src 'self'; "
    "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

Text = Annotated[str, StringConstraints(max_length=128, pattern=r"^[^\x00-\x1f]*$")]
Identities = Annotated[list[Text], Field(max_length=32)]
Document = dict[str, Any]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Revisioned(Payload):
    revision: Text


class Team(Payload):
    team: Annotated[int, Field(strict=True, ge=1, le=25599)]


class NetworkChange(Payload):
    mode: Literal["automatic", "static"]
    address: Annotated[str, Field(max_length=32)]

    @model_validator(mode="after")
    def usable_address(self):
        from .networking import validate_change

        validate_change(self.model_dump())
        return self


class NetworkToken(Payload):
    token: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class Device(Revisioned):
    identity: Text


class DeviceTune(Device):
    values: Document = {}
    reset: StrictBool = False


class DeviceMode(Device):
    mode_id: Text


class Debug(Revisioned):
    seconds: Annotated[int, Field(strict=True, ge=1, le=30)]


class ClearOverrides(Revisioned):
    path: Annotated[str, StringConstraints(max_length=512, pattern=r"^[^\x00-\x1f]*$")] = ""


class Configure(Revisioned):
    document: Document


class QualifyTiming(Revisioned):
    record: Document


class Rename(Device):
    name: Text


class Tune(Revisioned):
    name: Text
    values: Document = {}
    reset: StrictBool = False


class Mode(Revisioned):
    name: Text
    mode_id: Text


class Replace(Revisioned):
    name: Text
    identity: Text = ""


class Restore(Revisioned):
    generation: Text
    identities: Identities = []
    calibration_ids: Identities = []


class CalibrationBoard(Revisioned):
    board: Document
    options: Document


class CalibrationCameras(Revisioned):
    identities: Identities


class CalibrationAll(Payload):
    revision: Text = ""


class CalibrationStartAll(CalibrationAll):
    phase: Text = ""


class CalibrationCamera(Device):
    phase: Text = ""
    automatic: StrictBool = False


PAYLOADS: dict[str, type[Payload]] = {
    "nt/team": Team,
    "network/apply": NetworkChange,
    "network/confirm": NetworkToken,
    "network/revert": NetworkToken,
    "device/setup": Device,
    "device/tune": DeviceTune,
    "device/mode": DeviceMode,
    "standalone": Payload,
    "debug": Debug,
    "clear-overrides": ClearOverrides,
    "configure": Configure,
    "import": Configure,
    "qualify-timing": QualifyTiming,
    "rename": Rename,
    "tune": Tune,
    "mode": Mode,
    "replace": Replace,
    "restore": Restore,
    "calibration/board": CalibrationBoard,
    "calibration/select": CalibrationCameras,
    "calibration/apply": CalibrationCameras,
    "calibration/reset": CalibrationAll,
    "calibration/pause-all": CalibrationAll,
    "calibration/start-all": CalibrationStartAll,
    **{
        f"calibration/{action}": CalibrationCamera
        for action in ("start", "pause", "capture", "compute", "validate")
    },
}
Operation = Union[  # noqa: UP007 - Union[] accepts the generated tuple
    tuple(
        create_model(
            "".join(part.title() for part in name.replace("/", "-").split("-")) + "Operation",
            __config__=ConfigDict(extra="forbid"),
            operation=(Literal[name], ...),  # ty: ignore[invalid-type-form]
            payload=(payload, ...),
            request_id=(Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")], ...),
        )
        for name, payload in PAYLOADS.items()
    )
]


class Session(BaseModel):
    csrf: str
    client: str


class JobAccepted(BaseModel):
    job_id: str
    state: Literal["pending"] = "pending"


class BrowserSession:
    def __init__(self) -> None:
        self.id, self.csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        self.touched = time.monotonic()
        self.tokens, self.updated = 2.0, time.monotonic()
        self.previews = {}
        self.requests = {}


class Sessions:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.sessions: dict[str, BrowserSession] = {}
        self.jobs: dict[str, tuple[str, Future, float]] = {}
        self.lock = threading.RLock()

    def get(self, identity: str, *, create=False) -> BrowserSession | None:
        now = time.monotonic()
        with self.lock:
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
        with self.lock:
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


class BoundedJsonRequest(Request):
    async def body(self) -> bytes:
        if not hasattr(self, "_body"):
            length = self.headers.get("content-length", "")
            if (
                self.headers.get("transfer-encoding")
                or not length.isdigit()
                or not 0 < int(length) <= MAX_IMPORT_BODY
            ):
                raise HTTPException(400, "Bounded request body required")
        return await super().body()

    async def json(self) -> Any:
        if not hasattr(self, "_json"):

            def reject_constant(value):
                raise HTTPException(400, f"Invalid JSON numeric constant {value}")

            body = await self.body()
            document = json.loads(body, parse_constant=reject_constant)
            if len(body) > MAX_BODY and (
                not isinstance(document, dict) or document.get("operation") != "import"
            ):
                raise HTTPException(400, "Request body size exceeded")
            self._json = document
        return self._json


class BoundedJsonRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            return await handler(BoundedJsonRequest(request.scope, request.receive))

        return bounded


def _error(status: int, message: str, headers=None) -> JSONResponse:
    return JSONResponse({"error": message}, status, headers=headers)


def _validation_message(exc: RequestValidationError) -> str:
    error = exc.errors()[0]
    if "error" in error.get("ctx", {}):
        return str(error["ctx"]["error"])
    location = ".".join(str(part) for part in error["loc"][1:])
    return f"{location}: {error['msg']}" if location else error["msg"]


def create_app(runtime, *, assets: Path | None = None, allowed_hosts=()) -> FastAPI:
    # FastAPI's interactive docs load from a CDN and would collide with the operator docs at /docs.
    app = FastAPI(
        title="Spot Vision",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        generate_unique_id_function=lambda route: route.name,
    )
    app.router.route_class = BoundedJsonRoute
    app.state.assets = (assets or Path(str(files("spot_vision.web")))).resolve()
    app.state.allowed_hosts = {"localhost", "127.0.0.1", "::1", *allowed_hosts}
    sessions = app.state.sessions = Sessions(runtime)

    app.add_exception_handler(ValueError, lambda _, exc: _error(400, str(exc)))
    app.add_exception_handler(PermissionError, lambda _, exc: _error(403, str(exc)))
    app.add_exception_handler(
        StarletteHTTPException,
        lambda _, exc: _error(exc.status_code, exc.detail, getattr(exc, "headers", None)),
    )
    app.add_exception_handler(
        RequestValidationError, lambda _, exc: _error(400, _validation_message(exc))
    )

    def trusted_host(request: Request) -> bool:
        parsed = urlsplit("http://" + request.headers.get("host", ""))
        try:
            port = parsed.port or 80
        except ValueError:
            return False
        address, server_port = request.scope.get("server") or ("", 0)
        network = getattr(getattr(runtime, "network", None), "snapshot", {})
        return (
            parsed.hostname in {*app.state.allowed_hosts, address, network.get("hostname")}
            and port == server_port
            and not (
                parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            )
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if not trusted_host(request):
            response = _error(403, "Host is not an installed Spot address")
        else:
            response = await call_next(request)
        json_response = response.headers.get("content-type") == "application/json"
        docs = request.url.path == "/docs" or request.url.path.startswith("/docs/")
        response.headers["Cache-Control"] = "no-store" if json_response else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = DOCS_CSP if docs else CSP
        return response

    def optional_session(request: Request) -> BrowserSession | None:
        return sessions.get(request.cookies.get(COOKIE, ""))

    def browser_session(
        session: Annotated[BrowserSession | None, Depends(optional_session)],
    ) -> BrowserSession:
        if session is None:
            raise PermissionError("Browser session required")
        return session

    def mutation_session(request: Request) -> BrowserSession:
        if request.headers.get("origin") != "http://" + request.headers.get("host", ""):
            raise PermissionError("Same-origin request required")
        session = optional_session(request)
        if session is None or not secrets.compare_digest(
            request.headers.get("x-spot-csrf", ""), session.csrf
        ):
            raise PermissionError("Session/CSRF check failed")
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ConfigError("JSON body required")
        return session

    BrowserSessionDep = Annotated[BrowserSession, Depends(browser_session)]

    @app.get("/api/session")
    def create_session(request: Request, response: Response) -> Session:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise PermissionError("Same-origin browser session required")
        session = sessions.get(request.cookies.get(COOKIE, ""), create=True)
        if session is None:
            raise HTTPException(503, "Browser session limit reached")
        response.set_cookie(
            COOKIE, session.id, max_age=28800, path="/", httponly=True, samesite="strict"
        )
        return Session(csrf=session.csrf, client=session.id)

    @app.get("/health", include_in_schema=False)
    @app.get("/api/status")
    def status() -> dict:
        return runtime.status()

    @app.get("/api/calibrations")
    def calibrations(_: BrowserSessionDep) -> dict:
        records = runtime.configuration.state.data.get("calibrations", {})
        return {"calibrations": list(records.values())}

    def robot_configuration(defaults: bool) -> dict:
        config = runtime.configuration
        if config.manifest is None:
            raise ConfigError("Connect robot code before exporting its configuration")
        if defaults and config.robot_manifest is not None:
            profile = config.robot_manifest.profile
            return asdict(RobotConfiguration(profile.cameras, profile.processing))
        return asdict(config.export_configuration())

    @app.get("/api/robot-config")
    def robot_config(_: BrowserSessionDep) -> dict:
        return robot_configuration(defaults=False)

    @app.get("/api/robot-defaults")
    def robot_defaults(_: BrowserSessionDep) -> dict:
        return robot_configuration(defaults=True)

    @app.get("/api/export")
    def export(_: BrowserSessionDep) -> dict:
        return json.loads(runtime.store.export())

    @app.get("/api/support")
    def support(_: BrowserSessionDep) -> dict:
        return {
            "schema_version": 2,
            "status": runtime.status(),
            "configuration": json.loads(runtime.store.export()),
            "debug": runtime.debug,
        }

    @app.get("/api/jobs/{job_id}")
    def job(
        job_id: str, session: Annotated[BrowserSession | None, Depends(optional_session)]
    ) -> dict:
        with sessions.lock:
            job = sessions.jobs.get(job_id)
        if not session or not job or job[0] != session.id:
            raise HTTPException(404, "Job unavailable")
        future = job[1]
        if not future.done():
            return {"state": "pending"}
        try:
            return {"state": "applied", **future.result()}
        except Exception as exc:  # noqa: BLE001 - structured configuration rejection
            return {"state": "rejected", "error": str(exc)}

    @app.get("/api/frame/{identity}")
    def frame(
        identity: Annotated[str, PathParam(pattern=r"^[a-f0-9]{64}$")],
        session: BrowserSessionDep,
    ) -> dict:
        now = time.monotonic()
        with sessions.lock:
            if now - session.previews.get(identity, 0) < 1 / 25:
                raise HTTPException(429, "Preview rate exceeded")
            session.previews[identity] = now
        return runtime.frames.preview(identity, session.id + ":" + identity)

    @app.post("/api/operations", status_code=202)
    def submit(
        operation: Annotated[Operation, Body(discriminator="operation")],  # ty: ignore[invalid-type-form]
        session: Annotated[BrowserSession, Depends(mutation_session)],
    ) -> JobAccepted:
        payload = operation.payload.model_dump(exclude_unset=True)
        job_id = sessions.enqueue(session, operation.operation, payload, operation.request_id)
        return JobAccepted(job_id=job_id)

    app.mount("/", StaticFiles(directory=app.state.assets, html=True), name="web")
    return app


class HttpServer:
    """Binds on construction so the port is known and in use before serving starts."""

    def __init__(self, address, runtime, *, assets: Path | None = None, allowed_hosts=()):
        hosts = [*allowed_hosts]
        if address[0] not in {"", "0.0.0.0", "::"}:
            hosts.append(address[0])
        self.app = create_app(runtime, assets=assets, allowed_hosts=hosts)
        self.listener = socket.create_server(address)
        self.server_port = self.listener.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                log_config=None,
                access_log=False,  # Per-frame browser polling is deliberately absent from logs.
                limit_concurrency=16,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=2,
            )
        )

    def serve_forever(self) -> None:
        self.server.run(sockets=[self.listener])

    def shutdown(self) -> None:
        self.server.should_exit = True
