"""Shared-frame ChArUco fitting, independent validation and atomic group activation."""

from __future__ import annotations

import copy
import queue
import threading
import time
from dataclasses import asdict, dataclass, field

import numpy as np

from .calibration_session import CameraSession
from .charuco import (
    CalibrationOptions,
    CharucoBoardConfig,
    _diversity,
    _object_points,
    calibrate,
    detect_frame,
    make_board,
)
from .clock import wall_time_available
from .config import ConfigError
from .configuration import mode_signature, optical_controls


def validate_holdout(frames, board, intrinsics, *, max_rms_px=0.8, min_views=5) -> dict:
    """Fit board extrinsics only; held-out corners never refit camera intrinsics."""
    import cv2

    if len(frames) < min_views:
        return {
            "accepted": False,
            "reason": f"Capture at least {min_views} separate validation views",
            "views": len(frames),
            "rms_px": None,
        }
    if _diversity(frames) < 0.55:
        return {
            "accepted": False,
            "reason": "Increase independent validation view diversity",
            "views": len(frames),
            "rms_px": None,
        }
    matrix = np.array(intrinsics["camera_matrix"], dtype=float)
    distortion = np.array(intrinsics["distortion_coefficients"], dtype=float)
    squared = []
    for sample in frames:
        objects = _object_points(board, sample.ids)
        ok, rvec, tvec = cv2.solvePnP(
            objects, sample.image_points, matrix, distortion, flags=cv2.SOLVEPNP_ITERATIVE
        )
        if not ok or not np.isfinite(tvec).all() or tvec[2, 0] <= 0:
            return {
                "accepted": False,
                "reason": "Validation board pose failed",
                "views": len(frames),
                "rms_px": None,
            }
        projected = cv2.projectPoints(objects, rvec, tvec, matrix, distortion)[0].reshape(-1, 2)
        squared.extend(np.sum((projected - sample.image_points) ** 2, axis=1).tolist())
    rms = float(np.sqrt(np.mean(squared)))
    accepted = bool(np.isfinite(rms) and rms <= max_rms_px)
    return {
        "accepted": accepted,
        "reason": "Validation passed" if accepted else "Independent validation RMS exceeds limit",
        "views": len(frames),
        "rms_px": rms if np.isfinite(rms) else None,
        "limit_px": max_rms_px,
    }


@dataclass
class CalibrationCamera:
    identity: str
    mode_signature: str
    image_rotation_deg: int
    fit: CameraSession
    holdout: CameraSession
    generation: str
    optical_setup: dict = field(default_factory=dict)
    phase: str = "fit"
    automatic: bool = True
    last_frame: tuple | None = None
    last_accepted: tuple | None = None
    running: bool = False
    solving: bool = False
    intrinsics: dict | None = None
    report: dict | None = None
    validation: dict | None = None
    error: str = ""
    coverage: dict = field(default_factory=dict)


class CalibrationManager:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        saved = runtime.configuration.state.data.get("calibration_options", {})
        self.board = CharucoBoardConfig(**saved.get("board", {}))
        self.options = CalibrationOptions(**saved.get("options", {}))
        self.board.validate()
        self.options.validate()
        self.cameras: dict[str, CalibrationCamera] = {}
        self._lock = threading.RLock()
        self.stop_event = threading.Event()
        self.jobs: queue.Queue = queue.Queue(maxsize=8)
        self.capture_worker = threading.Thread(
            target=self._capture, name="charuco-capture", daemon=True
        )
        self.solve_worker = threading.Thread(target=self._solve, name="charuco-solve", daemon=True)
        self.last_progress = time.monotonic()
        self.active_job_started = None
        self.applied_generation = ""

    def command(self, action: str, payload: dict) -> dict:
        config = self.runtime.configuration
        if action == "apply":
            return self._apply(payload)
        with self._lock:
            if payload.get("revision", config.state.generation) != config.state.generation:
                raise ConfigError("revision conflict; fetch current configuration")
            if action == "board":
                board = CharucoBoardConfig(**payload["board"])
                options = CalibrationOptions(**payload["options"])
                board.validate()
                options.validate()
                make_board(board)
                if (
                    board.squares_x > 40
                    or board.squares_y > 40
                    or options.max_frames > 80
                    or options.min_frames < 15
                    or options.min_charuco_corners < 12
                    or options.min_markers < 4
                    or options.max_rms_px > 0.8
                ):
                    raise ConfigError("Board or view limit exceeded")
                data = copy.deepcopy(config.state.data)
                data["calibration_options"] = {"board": asdict(board), "options": asdict(options)}
                config._commit(data, payload["revision"])
                self.board, self.options, self.cameras = board, options, {}
            elif action == "select":
                identities = payload["identities"]
                if (
                    not isinstance(identities, list)
                    or not 0 <= len(identities) <= 8
                    or len(set(identities)) != len(identities)
                ):
                    raise ConfigError("Select one to eight distinct cameras")
                target = {}
                for identity in identities:
                    worker = self.runtime.workers.get(identity)
                    mode = self.runtime.modes.get(identity)
                    if (
                        worker is None
                        or not worker.verified
                        or mode is None
                        or mode.id == "preview"
                    ):
                        raise ConfigError("Verify each camera and assign a robot camera name")
                    signature = mode_signature(mode)
                    old = self.cameras.get(identity)
                    target[identity] = (
                        old
                        if old
                        and old.mode_signature == signature
                        and old.optical_setup == optical_controls(worker.readback)
                        and old.image_rotation_deg == worker.camera.image_rotation_deg
                        else CalibrationCamera(
                            identity,
                            signature,
                            worker.camera.image_rotation_deg,
                            CameraSession(identity),
                            CameraSession(identity),
                            config.state.generation,
                            optical_setup=optical_controls(worker.readback),
                        )
                    )
                self.cameras = target
            elif action == "reset":
                if any(c.solving for c in self.cameras.values()):
                    raise ConfigError("Wait for current solve before resetting the session")
                for identity, camera in list(self.cameras.items()):
                    self.cameras[identity] = CalibrationCamera(
                        identity,
                        camera.mode_signature,
                        camera.image_rotation_deg,
                        CameraSession(identity),
                        CameraSession(identity),
                        config.state.generation,
                        optical_setup=optical_controls(self.runtime.workers[identity].readback),
                    )
                self.applied_generation = ""
            elif action == "pause-all":
                for camera in self.cameras.values():
                    camera.running = False
            elif action == "start-all":
                phase = payload.get("phase", "fit")
                if phase not in {"fit", "holdout"} or not self.cameras:
                    raise ConfigError("Select cameras and a valid capture phase")
                for camera in self.cameras.values():
                    self._compatible(camera)
                    if camera.solving or (phase == "holdout" and camera.intrinsics is None):
                        raise ConfigError("Finish fitting every selected camera before validation")
                for camera in self.cameras.values():
                    camera.phase, camera.automatic, camera.running = phase, True, True
            else:
                camera = self.cameras.get(payload.get("identity"))
                if camera is None:
                    raise ConfigError("Select this camera for calibration first")
                self._compatible(camera)
                if action == "start":
                    if camera.solving:
                        raise ConfigError("Camera solve is pending")
                    camera.phase = payload.get("phase", "fit")
                    if camera.phase not in {"fit", "holdout"}:
                        raise ConfigError("Capture phase must be fit or holdout")
                    if camera.phase == "holdout" and camera.intrinsics is None:
                        raise ConfigError("Fit intrinsics before independent validation capture")
                    camera.automatic = payload.get("automatic", True)
                    camera.running = True
                    camera.error = ""
                elif action == "pause":
                    camera.running = False
                elif action == "capture":
                    self._accept(camera)
                elif action == "clear":
                    if camera.solving:
                        raise ConfigError("Camera solve is pending")
                    # Clearing fitting views also discards the fit and its validation.
                    if payload.get("phase") != "holdout":
                        camera.fit = CameraSession(camera.identity)
                        camera.intrinsics, camera.report = None, None
                        camera.phase, camera.running = "fit", False
                    camera.holdout = CameraSession(camera.identity)
                    camera.validation, camera.coverage, camera.error = None, {}, ""
                elif action in {"compute", "validate"}:
                    if camera.solving:
                        raise ConfigError("Camera solve is pending")
                    if action == "validate" and camera.intrinsics is None:
                        raise ConfigError("Fit intrinsics first")
                    camera.running, camera.solving = False, True
                    try:
                        self.jobs.put_nowait((camera, action, self.board, self.options))
                    except queue.Full as exc:
                        camera.solving = False
                        raise ConfigError("Calibration solve queue busy") from exc
                else:
                    raise ConfigError("Unknown calibration action")
            return self.status()

    def _apply(self, payload) -> dict:
        config = self.runtime.configuration
        with self._lock:
            if payload.get("revision") != config.state.generation:
                raise ConfigError("revision conflict; fetch current configuration")
            identities = payload["identities"]
            if not identities or len(set(identities)) != len(identities):
                raise ConfigError("Select a non-empty distinct passing group")
            records: list[dict] = []
            for identity in identities:
                camera = self.cameras.get(identity)
                if (
                    camera is None
                    or camera.solving
                    or camera.intrinsics is None
                    or not camera.report
                    or not camera.report["accepted"]
                    or not camera.validation
                    or not camera.validation["accepted"]
                ):
                    raise ConfigError("Every selected camera must pass fit and separate validation")
                self._compatible(camera)
                records.append(
                    {
                        "identity": identity,
                        "mode_signature": camera.mode_signature,
                        "image_rotation_deg": camera.image_rotation_deg,
                        "board": asdict(self.board),
                        "model": self.options.model,
                        "optical_controls": optical_controls(
                            self.runtime.workers[identity].readback
                        ),
                        "intrinsics": copy.deepcopy(camera.intrinsics),
                        "fit": copy.deepcopy(camera.report),
                        "holdout": copy.deepcopy(camera.validation),
                        "algorithm": "charuco-fit-holdout-v2",
                        "build": self.runtime.software.get("package_path"),
                        "saved_at": camera.intrinsics.get("calibrated_at")
                        if wall_time_available()
                        else None,
                    }
                )
            for camera in self.cameras.values():
                camera.running = False
            if not wall_time_available():
                for record in records:
                    record["intrinsics"]["calibrated_at"] = None
        # Native staging and durable writes must not hold the HTTP status lock.
        snapshot = config.calibration_group(
            records, payload["revision"], self.runtime.validate_calibration
        )
        with self._lock:
            self.applied_generation = snapshot.generation
        return self.status()

    def _compatible(self, camera) -> None:
        mode = self.runtime.modes.get(camera.identity)
        worker = self.runtime.workers.get(camera.identity)
        if (
            mode is None
            or mode_signature(mode) != camera.mode_signature
            or worker is None
            or not worker.verified
            or worker.camera.image_rotation_deg != camera.image_rotation_deg
            or optical_controls(worker.readback) != camera.optical_setup
        ):
            camera.running = False
            raise ConfigError("Camera or optical mode changed; restart this calibration session")

    def _accept(self, camera) -> None:
        session = camera.fit if camera.phase == "fit" else camera.holdout
        if camera.last_frame is None or camera.last_frame == camera.last_accepted:
            session.capture_reason = "Wait for a new board frame"
            return
        if camera.phase == "holdout" and camera.last_frame[2] <= getattr(
            camera, "fit_completed_ns", 0
        ):
            session.capture_reason = "Capture new validation views after fitting"
            return
        if camera.phase == "holdout" and len(session.samples) >= 20:
            session.capture_reason = "Validation capture limit reached"
            return
        if session.accept(self.options, automatic=camera.automatic, board=self.board):
            camera.last_accepted = camera.last_frame
            camera.validation = None
            if camera.phase == "fit":
                camera.intrinsics, camera.report = None, None
                camera.holdout.samples.clear()
            camera.coverage = session.coverage(self.board)

    def _capture(self) -> None:
        import cv2

        while not self.stop_event.wait(0.15):
            self.last_progress = time.monotonic()
            with self._lock:
                cameras = [c for c in self.cameras.values() if c.running and not c.solving]
                board, options = self.board, self.options
            for camera in cameras:
                try:
                    self._compatible(camera)
                    packet = self.runtime.frames.image(camera.identity)
                    if (
                        packet is None
                        or time.monotonic_ns() - packet.captured_monotonic_ns > 500_000_000
                    ):
                        raise ConfigError("Camera frame is stale")
                    key = packet.capture_epoch, packet.sequence, packet.captured_monotonic_ns
                    if key == camera.last_frame:
                        continue
                    detection = detect_frame(
                        cv2.cvtColor(packet.image, cv2.COLOR_YUV2BGR_YUY2), board, options
                    )
                    with self._lock:
                        if self.cameras.get(camera.identity) is not camera or not camera.running:
                            continue
                        session = camera.fit if camera.phase == "fit" else camera.holdout
                        session.last_detection = detection
                        camera.last_frame = key
                        if camera.automatic:
                            self._accept(camera)
                except Exception as exc:  # noqa: BLE001 - isolate backend/job failures at the worker boundary
                    with self._lock:
                        camera.error = str(exc)
                        camera.running = False

    def _solve(self) -> None:
        while not self.stop_event.is_set():
            try:
                camera, action, board, options = self.jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            self.active_job_started = time.monotonic()
            try:
                if action == "compute":
                    intrinsics, report = calibrate(list(camera.fit.samples), board, options)
                    # Reject non-finite backend output before HTTP JSON/state can
                    # expose it; a failed solve must never appear as a passing fit.
                    import json

                    json.dumps(
                        {"intrinsics": intrinsics, "report": asdict(report)}, allow_nan=False
                    )
                    with self._lock:
                        camera.intrinsics, camera.report = intrinsics, asdict(report)
                        camera.holdout = CameraSession(camera.identity)
                        camera.fit_completed_ns = time.monotonic_ns()
                        camera.validation = None
                else:
                    validation = validate_holdout(
                        list(camera.holdout.samples),
                        board,
                        camera.intrinsics,
                        max_rms_px=options.max_rms_px,
                    )
                    with self._lock:
                        camera.validation = validation
            except Exception as exc:  # noqa: BLE001 - isolate backend/job failures at the worker boundary
                with self._lock:
                    camera.error = str(exc)
            finally:
                with self._lock:
                    camera.solving = False
                    self.active_job_started = None

    def status(self) -> dict:
        with self._lock:
            return {
                "board": asdict(self.board),
                "options": asdict(self.options),
                "applied_generation": self.applied_generation,
                "cameras": {
                    identity: {
                        "running": c.running,
                        "solving": c.solving,
                        "phase": c.phase,
                        "fit_views": len(c.fit.samples),
                        "holdout_views": len(c.holdout.samples),
                        "fit": c.report,
                        "holdout": c.validation,
                        "board_detected": (c.fit if c.phase == "fit" else c.holdout).last_detection
                        is not None,
                        "reason": c.error
                        or (c.fit if c.phase == "fit" else c.holdout).capture_reason,
                        "coverage": copy.deepcopy(c.coverage),
                    }
                    for identity, c in self.cameras.items()
                },
            }

    def start(self) -> None:
        self.capture_worker.start()
        self.solve_worker.start()

    def close(self) -> None:
        self.stop_event.set()
        for worker in (self.capture_worker, self.solve_worker):
            if worker.is_alive():
                worker.join(timeout=3)
