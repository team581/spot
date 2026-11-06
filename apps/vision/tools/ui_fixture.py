#!/usr/bin/env python3
"""Deterministic development-only GUI data. No USB, NT or production state access.

uv run --no-sync python apps/vision/tools/ui_fixture.py --port 5808
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import time
import uuid
from concurrent.futures import Future
from types import SimpleNamespace

import cv2
import numpy as np

from spot_vision.http_server import HttpServer
from spot_vision.protocol_models import RobotConfiguration


class FixtureRuntime:
    def __init__(self, scenario="mixed"):
        self.scenario = scenario
        self.revision = "fixture-generation-1"
        self.started = time.monotonic()
        self.cameras = []
        for index, name in enumerate(("front-left", "front-right", "rear", "USB-A3")):
            identity = hashlib.sha256(name.encode()).hexdigest()
            controls = [
                self.control("exposure_time_absolute", "Exposure", 2, 200, 12, "ms", 0.1),
                self.control("gain", "Gain", 0, 100, 30, "", 1),
                self.control("brightness", "Brightness", 0, 100, 50, "", 1),
            ]
            self.cameras.append(
                {
                    "identity": identity,
                    "display_id": "USB-A" + str(index),
                    "name": name,
                    "logical_name": name if index < 3 else None,
                    "connected": index != 2,
                    "present": index != 2,
                    "calibrated": index != 1,
                    "controls": controls,
                    "required": index < 2,
                    "warning": "Calibration required" if index == 1 else "",
                    "fault": "Disconnected" if index == 2 else "",
                    "calibration_id": "fixture-id",
                    "age_s": 0.035 if index != 2 else 4.1,
                    "unique_serial": index < 2,
                    "serial": "fixture-serial-" + str(index),
                    "topology": "usb-fixture:" + str(index),
                    "capture_node": "/dev/fixture" + str(index),
                    "mode_id": "640x480",
                    "mode_signature": "fixture-optical-mode",
                    "allowed_modes": [
                        {
                            "id": "640x480",
                            "width": 640,
                            "height": 480,
                            "fps": 30,
                            "pixel_format": "MJPG",
                            "supported": True,
                        }
                    ],
                    "geometry": {"translation": [0.31, 0.2, 0.5], "quaternion": [1, 0, 0, 0]},
                    "metrics": {
                        "fps_capture": 30,
                        "fps_detect": 18,
                        "detected": 100,
                        "detect_age_s": 0.03,
                        "overwritten_before_processing": 3,
                        "driver_sequence_gaps": 0,
                    },
                }
            )
        if scenario == "empty":
            self.cameras = []
        image = np.full((480, 640, 3), (57, 66, 69), np.uint8)
        cv2.rectangle(image, (80, 100), (560, 350), (93, 105, 112), -1)
        cv2.line(image, (0, 430), (640, 220), (152, 162, 170), 3)
        cv2.putText(
            image,
            "SYNTHETIC GUI FIXTURE",
            (75, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (220, 230, 235),
            2,
        )
        # Illustrative corners are not a real detector or acceptance fixture.
        self.tags = [
            {
                "id": 1,
                "corners": [[280, 180], [350, 180], [350, 250], [280, 250]],
                "used": True,
                "reason": "",
                "distance_m": 3.1,
                "error_px": 0.2,
            }
        ]
        self.jpeg = cv2.imencode(".jpg", image)[1].tobytes()
        # The fixture image never changes, so subscribers only need the current frame.
        self.frames = SimpleNamespace(
            subscribe=lambda identity, notify: lambda: None, frame=self.frame
        )
        self.configuration = SimpleNamespace(
            state=SimpleNamespace(data={"development_fixture": True}),
            export_configuration=lambda: RobotConfiguration(),
        )
        self.debug = {}
        self.calibration_sessions = {
            camera["identity"]: {
                "phase": "fit",
                "fit_views": 24,
                "holdout_views": 8,
                "fit": {"accepted": True, "rms_reprojection_error_px": 0.31},
                "holdout": {"accepted": index == 0, "rms_px": 0.43 if index == 0 else 1.1},
                "coverage": {
                    "coverage_progress": 0.75,
                    "coverage_particles": [
                        {"x": x / 10, "y": y / 10, "progress": 1 if x < 5 else 0.5}
                        for x in range(2, 9)
                        for y in range(2, 8)
                    ],
                },
                "board_detected": True,
                "running": False,
                "solving": False,
                "reason": "Validation passed"
                if index == 0
                else "Independent validation RMS exceeds limit",
            }
            for index, camera in enumerate(self.cameras[:2])
        }
        self.calibration_applied = ""

    @staticmethod
    def control(name, label, minimum, maximum, value, unit, factor):
        return {
            "name": name,
            "label": label,
            "min": minimum,
            "max": maximum,
            "step": 1 if factor == 1 else factor,
            "value": value,
            "unit": unit,
            "factor": factor,
            "allowed": True,
            "writable": True,
            "required": False,
            "default": value,
            "options": [],
            "reason": "",
            "flags": [],
        }

    def frame(self, identity):
        camera = next(c for c in self.cameras if c["identity"] == identity)
        return {
            "sequence": 101,
            "capture_epoch": "fixture-capture",
            "generation": self.revision,
            "width": 640,
            "height": 480,
            "age_s": camera["age_s"],
            "stale": not camera["connected"],
            "processed": True,
            "tags": self.tags if camera["connected"] else [],
            "candidates": [
                {
                    "translation": [1, 2, 0.5],
                    "quaternion": [1, 0, 0, 0],
                    "method": 2,
                    "ids": [1],
                    "error_px": 0.2,
                    "distance_m": 3.1,
                }
            ],
        }, self.jpeg

    def status(self):
        return {
            "revision": self.revision,
            "applied_generation": self.revision,
            "cameras": copy.deepcopy(self.cameras),
            "names": ["front-left", "front-right", "rear", "turret"] if self.cameras else [],
            "fresh": False,
            "has_configuration": self.scenario == "mixed",
            "overrides": self.overrides(),
            "clock": {
                "state": "Waiting",
                "offset_us": None,
                "update_age_s": None,
                "sync_epoch": 0,
                "discontinuities": 0,
            },
            "software": {
                "package_path": "development-fixture",
                "configuration_revision": "SYNTHETIC",
                "process_started_at": None,
            },
            "uptime_s": time.monotonic() - self.started,
            "system": {
                "cpu_percent": 22,
                "gpu_percent": 15,
                "temperature_c": 48,
                "memory_used_gb": 2.1,
                "memory_total_gb": 8,
            },
            "startup": {
                "state_load_s": 0.04,
                "enumeration_s": 0.15,
                "first_processed_frame_s": 0.35,
            },
            "faults": ["Development fixture; no hardware qualification"],
            "history": [
                {
                    "generation": "fixture-previous-calibration",
                    "active": False,
                    "cameras": [
                        {
                            "identity": c["identity"],
                            "mode_signature": "fixture-optical-mode",
                            "id": "fixture-record-" + str(i),
                            "saved_at": None,
                        }
                        for i, c in enumerate(self.cameras[:2])
                    ],
                }
            ],
            "endpoint": {
                "hostname": "spot-fixture",
                "local_addresses": ["127.0.0.1"],
                "configured": None,
                "mode": "NT4 client",
                "team": 581,
                "server": None,
                "port": 5808,
            },
            "field": {
                "origin": "blue-wall-right",
                "length": 16,
                "width": 8,
                "tags": [
                    {"id": 1, "size": 0.1651, "translation": [4, 2, 1], "quaternion": [1, 0, 0, 0]}
                ],
            },
            "calibration": {
                "board": {
                    "squares_x": 15,
                    "squares_y": 15,
                    "square_length_m": 0.03,
                    "marker_length_m": 0.022,
                    "dictionary": "DICT_4X4_250",
                },
                "options": {
                    "model": "plumb_bob",
                    "min_frames": 15,
                    "min_corners": 12,
                    "min_markers": 4,
                    "max_frames": 80,
                    "max_rms_px": 0.8,
                },
                "cameras": copy.deepcopy(self.calibration_sessions),
                "applied_generation": self.calibration_applied,
            },
        }

    def overrides(self):
        """Tuned fixture controls stand in for saved dashboard overrides."""
        return [
            {
                "path": f"cameras/{camera['logical_name']}/controls/{control['name']}",
                "value": {"name": control["name"], "default_value": control["value"]},
                "code_value": {"name": control["name"], "default_value": control["default"]},
                "code_changed": False,
            }
            for camera in self.cameras
            if camera["logical_name"]
            for control in camera["controls"]
            if control["value"] != control["default"]
        ]

    def submit(self, operation, payload):
        future = Future()
        if self.scenario != "mixed":
            future.set_exception(
                ValueError("Connect robot code once to load its camera configuration")
            )
            return future
        if payload.get("revision", self.revision) != self.revision:
            future.set_exception(ValueError("Revision conflict; reconcile current values"))
            return future
        if operation.startswith("network/"):
            future.set_result({"result": {}})
            return future
        if operation == "camera/tune":
            camera = next(c for c in self.cameras if c["logical_name"] == payload["name"])
            for control in camera["controls"]:
                if payload.get("reset"):
                    control["value"] = control["default"]
                elif control["name"] in payload.get("values", {}):
                    control["value"] = payload["values"][control["name"]]
        elif operation == "configuration/clear-overrides":
            for camera in self.cameras:
                for control in camera["controls"]:
                    path = f"cameras/{camera['logical_name']}/controls/{control['name']}"
                    if path.startswith(payload.get("path", "")):
                        control["value"] = control["default"]
        elif operation == "calibration/apply":
            identities = payload["identities"]
            if not identities or any(
                not self.calibration_sessions[i]["holdout"]["accepted"] for i in identities
            ):
                future.set_exception(
                    ValueError("Every selected camera must pass separate validation")
                )
                return future
            self.calibration_applied = "fixture-calibration-applied"
        elif operation in {"calibration/start-all", "calibration/pause-all"}:
            for session in self.calibration_sessions.values():
                session["running"] = operation == "calibration/start-all"
        elif operation.startswith("calibration/"):
            session = self.calibration_sessions.get(payload.get("identity"))
            if session and operation in {"calibration/start", "calibration/pause"}:
                session["running"] = operation == "calibration/start"
                session["phase"] = payload.get("phase", session["phase"])
        elif operation == "device/name":
            camera = next(c for c in self.cameras if c["identity"] == payload["identity"])
            camera["logical_name"] = camera["name"] = payload["name"]
        self.revision = "fixture-" + uuid.uuid4().hex
        future.set_result(
            {
                "revision": self.revision,
                "applied_generation": self.revision,
                "controls": {
                    c["name"]: c["value"]
                    for c in next(
                        (
                            cam["controls"]
                            for cam in self.cameras
                            if cam["logical_name"] == payload.get("name")
                        ),
                        [],
                    )
                },
            }
        )
        return future


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5808)
    parser.add_argument("--scenario", choices=("mixed", "empty"), default="mixed")
    args = parser.parse_args()
    server = HttpServer(("127.0.0.1", args.port), FixtureRuntime(args.scenario))
    print(f"SYNTHETIC GUI FIXTURE http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
