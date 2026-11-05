"""Installed HTTP boundary. Mutations wait for the runtime's configuration worker."""

import asyncio
import json
import re
import socket
import struct
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import uvicorn
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import HTTPConnection

from .protocol_models import RobotConfiguration

MAX_BODY = 256 * 1024
MAX_IMPORT_BODY = 2 * 1024 * 1024
ACKNOWLEDGEMENT_TIMEOUT_S = 30
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


class NtEndpoint(Payload):
    """Connect to the robot by FRC team number or by hostname/IPv4 address (exactly one)."""

    team: Annotated[int, Field(strict=True, ge=1, le=25599)] | None = None
    server: Annotated[str, Field(pattern=r"^[A-Za-z0-9.-]{1,253}$")] | None = None

    @model_validator(mode="after")
    def one_endpoint(self):
        if (self.team is None) == (self.server is None):
            raise ValueError("Set exactly one of team or server")
        return self


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


# Each operation is served at POST /api/<operation> and runs on the runtime's worker.
OPERATIONS: dict[str, type[Payload]] = {
    "nt/endpoint": NtEndpoint,
    "network/apply": NetworkChange,
    "network/confirm": NetworkToken,
    "network/revert": NetworkToken,
    "standalone": Payload,
    "device/setup": Device,
    "device/tune": DeviceTune,
    "device/mode": DeviceMode,
    "device/name": Rename,
    "camera/tune": Tune,
    "camera/mode": Mode,
    "camera/replace": Replace,
    "configuration/apply": Configure,
    "configuration/import": Configure,
    "configuration/clear-overrides": ClearOverrides,
    "configuration/restore": Restore,
    "configuration/qualify-timing": QualifyTiming,
    "debug/record": Debug,
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


class NetworkApplied(BaseModel):
    result: dict[str, Any]


class Applied(BaseModel):
    revision: str
    applied_generation: str | None
    result: dict[str, Any] | None = None
    controls: dict[str, float] | None = None


class BoundedJsonRequest(Request):
    async def body(self) -> bytes:
        if not hasattr(self, "_body"):
            limit = MAX_IMPORT_BODY if self.url.path == "/api/configuration/import" else MAX_BODY
            length = self.headers.get("content-length", "")
            if (
                self.headers.get("transfer-encoding")
                or not length.isdigit()
                or not 0 < int(length) <= limit
            ):
                raise HTTPException(400, "Bounded request body required")
        return await super().body()

    async def json(self) -> Any:
        if not hasattr(self, "_json"):

            def reject_constant(value):
                raise HTTPException(400, f"Invalid JSON numeric constant {value}")

            self._json = json.loads(await self.body(), parse_constant=reject_constant)
        return self._json


class BoundedJsonRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            return await handler(BoundedJsonRequest(request.scope, request.receive))

        return bounded


def same_origin_json(request: Request) -> None:
    """Cross-site browsers cannot send a matching Origin or a JSON body without CORS."""
    if request.headers.get("origin") != "http://" + request.headers.get("host", ""):
        raise PermissionError("Same-origin request required")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise HTTPException(400, "JSON body required")


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
    app.state.assets = (assets or Path(str(files("spot_vision.web")))).resolve()
    app.state.allowed_hosts = {"localhost", "127.0.0.1", "::1", *allowed_hosts}

    app.add_exception_handler(ValueError, lambda _, exc: _error(400, str(exc)))
    app.add_exception_handler(PermissionError, lambda _, exc: _error(403, str(exc)))
    app.add_exception_handler(
        StarletteHTTPException,
        lambda _, exc: _error(exc.status_code, exc.detail, getattr(exc, "headers", None)),
    )
    app.add_exception_handler(
        RequestValidationError, lambda _, exc: _error(400, _validation_message(exc))
    )

    def trusted_host(request: HTTPConnection) -> bool:
        """Reject DNS-rebinding hostnames; the service has no other authentication."""
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

    @app.get("/api/status")
    def status() -> dict:
        return runtime.status()

    @app.get("/api/configuration")
    def configuration() -> dict:
        return json.loads(runtime.store.export())

    @app.get("/api/calibrations")
    def calibrations() -> dict:
        records = runtime.configuration.state.data.get("calibrations", {})
        return {"calibrations": list(records.values())}

    @app.get("/api/robot/configuration")
    def robot_configuration() -> dict:
        return asdict(runtime.configuration.export_configuration())

    @app.get("/api/robot/defaults")
    def robot_defaults() -> dict:
        manifest = runtime.configuration.robot_manifest
        if manifest is None:
            raise ValueError("Connect robot code before exporting its configuration")
        return asdict(RobotConfiguration(manifest.profile.cameras, manifest.profile.processing))

    @app.get("/api/support")
    def support() -> dict:
        return {
            "schema_version": 2,
            "status": runtime.status(),
            "configuration": json.loads(runtime.store.export()),
            "debug": runtime.debug,
        }

    @app.websocket("/api/frames/{identity}")
    async def frames(websocket: WebSocket, identity: str) -> None:
        """Push each new preview as one binary message: u32 header length, JSON header, JPEG."""
        # Browsers do not apply CORS to WebSockets, so check the page origin explicitly.
        if (
            not trusted_host(websocket)
            or websocket.headers.get("origin") != "http://" + websocket.headers.get("host", "")
            or not re.fullmatch(r"[a-f0-9]{64}", identity)
        ):
            await websocket.close(code=1008)
            return
        loop, ready = asyncio.get_running_loop(), asyncio.Event()

        def notify():
            if not loop.is_closed():
                loop.call_soon_threadsafe(ready.set)

        try:
            unsubscribe = runtime.frames.subscribe(identity, notify)
        except ValueError:
            await websocket.close(code=1013)
            return
        await websocket.accept()
        disconnected = asyncio.ensure_future(websocket.receive())
        try:
            sent = None
            ready.set()  # Send the current frame without waiting for the next encode.
            while True:
                waiting = asyncio.ensure_future(ready.wait())
                await asyncio.wait({waiting, disconnected}, return_when=asyncio.FIRST_COMPLETED)
                if disconnected.done():
                    waiting.cancel()
                    return
                ready.clear()
                frame = runtime.frames.frame(identity)
                if frame is None:
                    continue
                header, image = frame
                key = (header["capture_epoch"], header["sequence"], header["processed"])
                if key == sent:
                    continue
                encoded = json.dumps(header, allow_nan=False, separators=(",", ":")).encode()
                await websocket.send_bytes(struct.pack(">I", len(encoded)) + encoded + image)
                sent = key
        except WebSocketDisconnect:
            pass
        finally:
            disconnected.cancel()
            unsubscribe()

    operations = APIRouter(
        prefix="/api", route_class=BoundedJsonRoute, dependencies=[Depends(same_origin_json)]
    )

    def operation_endpoint(operation: str, model: type[Payload]):
        response = NetworkApplied if operation.startswith("network/") else Applied

        def endpoint(payload: model) -> response:  # ty: ignore[invalid-type-form]
            future = runtime.submit(operation, payload.model_dump(exclude_unset=True))
            try:
                return response(**future.result(ACKNOWLEDGEMENT_TIMEOUT_S))
            except FutureTimeoutError:
                raise HTTPException(
                    504, "Acknowledgement pending; read current values before retrying"
                ) from None

        return endpoint

    for operation, model in OPERATIONS.items():
        operations.post(f"/{operation}", name=operation.replace("/", "_").replace("-", "_"))(
            operation_endpoint(operation, model)
        )
    app.include_router(operations)
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
                # Each open camera preview holds a WebSocket connection.
                limit_concurrency=32,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=2,
            )
        )

    def serve_forever(self) -> None:
        self.server.run(sockets=[self.listener])

    def shutdown(self) -> None:
        self.server.should_exit = True
