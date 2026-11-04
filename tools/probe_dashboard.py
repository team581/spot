"""Disposable laptop-only observer for Spot probe and daemon bring-up."""

from __future__ import annotations

import argparse
import curses
import ipaddress
import json
import math
import os
import re
import shlex
import statistics
import subprocess
import sys
import tempfile
import termios
import threading
import time
import urllib.request
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
MAX_LINE = 1024 * 1024
ALPHA_HOST = "team581@192.168.69.170"
ALPHA_MAC_ADDRESS = "192.168.69.171/24"


def clean(text: str) -> str:
    return "".join(c for c in ANSI.sub("", text) if c.isprintable())


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def number(value) -> bool:
    try:
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    except OverflowError:
        return False


def valid_record(value) -> bool:
    if not isinstance(value, dict):
        return False
    if not all(
        number(value.get(key)) and value[key] >= 0
        for key in ("sequence", "capture_fps", "detect_ms", "total_ms", "dropped_before_processing")
    ):
        return False
    tags = value.get("tags")
    return isinstance(tags, list) and all(
        isinstance(tag, dict)
        and isinstance(tag.get("id"), int)
        and number(tag.get("hamming"))
        and number(tag.get("decision_margin"))
        for tag in tags
    )


@dataclass
class State:
    started: float = field(default_factory=time.monotonic)
    latest: dict | None = None
    last_received: float | None = None
    samples: deque = field(default_factory=lambda: deque(maxlen=5000))
    events: deque = field(default_factory=lambda: deque(maxlen=20))
    count: int = 0
    tagged: int = 0
    total_ms: float = 0.0
    maximum_ms: float = 0.0
    lock: threading.RLock = field(default_factory=threading.RLock)

    def event(self, message: str, now: float) -> None:
        self.events.append(f"{max(0, now - self.started):7.1f}s {clean(message)[:240]}")

    def ingest(self, line: str, now: float, diagnostic: bool = False) -> None:
        with self.lock:
            stripped = line.strip()
            if not stripped:
                return
            if diagnostic or not stripped.startswith("{"):
                self.event(stripped, now)
                return
            try:
                record = json.loads(stripped)
            except (ValueError, RecursionError):
                self.event("Malformed JSON record", now)
                return
            if not valid_record(record):
                self.event("Diagnostic or invalid observation: " + stripped, now)
                return
            previous_ids = {t["id"] for t in self.latest["tags"]} if self.latest else set()
            current_ids = {t["id"] for t in record["tags"]}
            if self.latest and record["sequence"] <= self.latest["sequence"]:
                self.event("Sequence reset or non-increasing sequence", now)
            for tag_id in sorted(current_ids - previous_ids):
                self.event(f"Tag {tag_id} appeared", now)
            for tag_id in sorted(previous_ids - current_ids):
                self.event(f"Tag {tag_id} disappeared", now)
            self.latest = record
            self.last_received = now
            self.samples.append((now, record["detect_ms"], record["total_ms"]))
            self.count += 1
            self.tagged += bool(record["tags"])
            self.total_ms += record["total_ms"]
            self.maximum_ms = max(self.maximum_ms, record["total_ms"])

    def lines(self, host: str, camera: str, now: float, status: str) -> list[str]:
        with self.lock:
            while self.samples and now - self.samples[0][0] > 5:
                self.samples.popleft()
            stale = self.last_received is not None and now - self.last_received >= 2
            freshness = (
                "Waiting for first result"
                if self.latest is None
                else "STALE: no new results for two seconds"
                if stale
                else "No tags in latest result"
                if not self.latest["tags"]
                else "Fresh results"
            )
            lines = [
                f"Spot prototype | {host} / {camera} | {now - self.started:.1f}s | {status}",
                freshness,
            ]
            if self.latest:
                r = self.latest
                window = min(5, max(0.001, now - self.started))
                rate = len(self.samples) / window
                lines += [
                    (
                        f"Sequence {r['sequence']} | Capture {r['capture_fps']:.1f} FPS | "
                        f"Received {rate:.1f}/s | Overwrites {r['dropped_before_processing']}"
                    ),
                    "Received rate is observer-measured and affected by SSH buffering.",
                    f"Detector {r['detect_ms']:.2f} ms | Probe processing {r['total_ms']:.2f} ms",
                    "Probe processing excludes capture and publication.",
                ]
                if self.samples:
                    for index, label in ((1, "Detector"), (2, "Probe processing")):
                        values = [sample[index] for sample in self.samples]
                        lines.append(
                            f"{label} rolling median/p95: {statistics.median(values):.2f} / "
                            f"{percentile(values, 0.95):.2f} ms (5s, max 5000)"
                        )
                lines += ["", "TAG ID      HAMMING      DECISION MARGIN"]
                for tag in sorted(r["tags"], key=lambda t: t["id"])[:12]:
                    lines.append(f"{tag['id']:<12}{tag['hamming']:<13}{tag['decision_margin']:.2f}")
                if len(r["tags"]) > 12:
                    lines.append(f"... {len(r['tags']) - 12} additional detections in raw log")
            return lines


@dataclass
class CameraView:
    latest: dict | None = None
    last_received: float | None = None
    status: dict = field(default_factory=dict)
    samples: deque = field(default_factory=lambda: deque(maxlen=5000))


@dataclass
class DaemonState:
    started: float = field(default_factory=time.monotonic)
    cameras: dict[str, CameraView] = field(default_factory=dict)
    events: deque = field(default_factory=lambda: deque(maxlen=20))
    count: int = 0
    tagged: int = 0
    total_ms: float = 0.0
    maximum_ms: float = 0.0
    temperature_c: float | None = None
    last_status: float | None = None
    viewer_status: str = "Waiting for viewer"
    viewer_ready: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def event(self, message: str, now: float) -> None:
        self.events.append(f"{max(0, now - self.started):7.1f}s {clean(message)[:240]}")

    def _camera(self, camera_id: str) -> CameraView:
        return self.cameras.setdefault(camera_id, CameraView())

    def ingest(self, line: str, now: float, diagnostic: bool = False) -> None:
        with self.lock:
            stripped = line.strip()
            if not stripped:
                return
            if diagnostic:
                self.event(stripped, now)
                return
            try:
                record = json.loads(stripped)
            except (ValueError, RecursionError):
                self.event(
                    stripped if not stripped.startswith("{") else "Malformed JSON record", now
                )
                return
            prototype = record.get("prototype") if isinstance(record, dict) else None
            if not isinstance(prototype, dict):
                message = record.get("message") if isinstance(record, dict) else stripped
                self.event(str(message), now)
                return
            kind = prototype.get("type")
            if kind == "viewer":
                if prototype.get("ready"):
                    self.viewer_status = f"Viewer ready on port {prototype.get('port')}"
                    self.viewer_ready.set()
                else:
                    self.viewer_status = "Viewer unavailable: " + str(
                        prototype.get("error", "unknown error")
                    )
                    self.event(self.viewer_status, now)
                return
            if kind == "status":
                cameras = prototype.get("cameras")
                if not isinstance(cameras, dict):
                    self.event("Invalid daemon status record", now)
                    return
                self.last_status = now
                if number(prototype.get("temperature_c")):
                    self.temperature_c = prototype["temperature_c"]
                for camera_id, status in cameras.items():
                    if not isinstance(camera_id, str) or not isinstance(status, dict):
                        continue
                    camera = self._camera(camera_id)
                    previous_state = camera.status.get("state")
                    previous_error = camera.status.get("error")
                    camera.status = status
                    current_state = status.get("state")
                    if previous_state and current_state != previous_state:
                        self.event(f"{camera_id} state {previous_state} -> {current_state}", now)
                    error = status.get("error")
                    if error and error != previous_error:
                        self.event(f"{camera_id}: {error}", now)
                return
            if kind != "frame" or not self._valid_frame(prototype):
                self.event("Diagnostic or invalid prototype record", now)
                return
            camera_id = prototype["camera_id"]
            camera = self._camera(camera_id)
            previous_ids = {tag["id"] for tag in camera.latest["tags"]} if camera.latest else set()
            current_ids = {tag["id"] for tag in prototype["tags"]}
            if camera.latest and prototype["sequence"] <= camera.latest["sequence"]:
                self.event(f"{camera_id} sequence reset or non-increasing sequence", now)
            for tag_id in sorted(current_ids - previous_ids):
                self.event(f"{camera_id} tag {tag_id} appeared", now)
            for tag_id in sorted(previous_ids - current_ids):
                self.event(f"{camera_id} tag {tag_id} disappeared", now)
            timing = prototype["timing"]
            camera.latest = prototype
            camera.last_received = now
            camera.samples.append((now, timing["detect_ms"], timing["total_ms"]))
            camera.status.update(
                {
                    "state": prototype.get("state", camera.status.get("state", "UNKNOWN")),
                    "fps_capture": prototype["capture_fps"],
                    "fps_detect": prototype["detect_fps"],
                }
            )
            self.count += 1
            self.tagged += bool(prototype["tags"])
            self.total_ms += timing["total_ms"]
            self.maximum_ms = max(self.maximum_ms, timing["total_ms"])

    @staticmethod
    def _valid_frame(value: dict) -> bool:
        timing = value.get("timing")
        tags = value.get("tags")
        return (
            isinstance(value.get("camera_id"), str)
            and number(value.get("sequence"))
            and value["sequence"] >= 0
            and number(value.get("capture_fps"))
            and value["capture_fps"] >= 0
            and number(value.get("detect_fps"))
            and value["detect_fps"] >= 0
            and isinstance(timing, dict)
            and all(
                number(timing.get(key)) and timing[key] >= 0 for key in ("detect_ms", "total_ms")
            )
            and isinstance(tags, list)
            and all(
                isinstance(tag, dict)
                and isinstance(tag.get("id"), int)
                and number(tag.get("hamming"))
                and number(tag.get("decision_margin"))
                for tag in tags
            )
        )

    def lines(self, host: str, _camera: str, now: float, status: str) -> list[str]:
        with self.lock:
            temperature = "unknown" if self.temperature_c is None else f"{self.temperature_c:.1f} C"
            service_stale = self.last_status is not None and now - self.last_status >= 2
            lines = [
                f"Spot daemon prototype | {host} | {now - self.started:.1f}s | {status}",
                f"{self.viewer_status} | Jetson {temperature}"
                + (" | STATUS STALE" if service_stale else ""),
                "",
            ]
            lines.append(
                "CAMERA       STATE/AGE       SEQ  TAGS       CAP   DET   RX    TOTAL  DROPS C/D/O/Q/S"
            )
            summary_lines = []
            detail_lines = []
            for camera_id, camera in self.cameras.items():
                while camera.samples and now - camera.samples[0][0] > 5:
                    camera.samples.popleft()
                if camera.latest is None:
                    age = "waiting"
                    sequence, tags, total = 0, "-", 0.0
                else:
                    stale = camera.last_received is not None and now - camera.last_received >= 2
                    age = "stale" if stale else ("tags" if camera.latest["tags"] else "no-tags")
                    sequence = camera.latest["sequence"]
                    tags = ",".join(str(tag["id"]) for tag in camera.latest["tags"]) or "-"
                    total = camera.latest["timing"]["total_ms"]
                camera_status = camera.status
                window = min(5, max(0.001, now - self.started))
                rate = len(camera.samples) / window
                drops = camera.latest.get("drops", {}) if camera.latest else {}
                drop_text = "/".join(
                    str(
                        drops.get(
                            key,
                            camera_status.get(
                                {
                                    "capture": "capture_failures",
                                    "decode": "decode_failures",
                                    "overwrite": "overwritten_before_processing",
                                    "result_queue": "result_queue_drops",
                                    "sequence": "driver_sequence_gaps",
                                }[key],
                                0,
                            ),
                        )
                    )
                    for key in ("capture", "decode", "overwrite", "result_queue", "sequence")
                )
                summary_lines.append(
                    f"{camera_id[:12]:<12} {str(camera_status.get('state', 'UNKNOWN'))[:8]:<8}/"
                    f"{age:<7} {sequence:>5}  {tags[:10]:<10} "
                    f"{float(camera_status.get('fps_capture', 0)):<5.1f} "
                    f"{float(camera_status.get('fps_detect', 0)):<5.1f} {rate:<5.1f} "
                    f"{total:<6.1f} {drop_text}"
                )
                if camera.samples:
                    detect = [sample[1] for sample in camera.samples]
                    totals = [sample[2] for sample in camera.samples]
                    detail_lines.append(
                        f"  {camera_id} rolling detector p50/p95 "
                        f"{statistics.median(detect):.2f}/{percentile(detect, 0.95):.2f} ms; "
                        f"total {statistics.median(totals):.2f}/{percentile(totals, 0.95):.2f} ms"
                    )
                error = camera_status.get("error")
                if error:
                    detail_lines.append(f"  {camera_id} error: {error}")
            lines.extend(summary_lines)
            lines.extend(detail_lines)
            tags_shown = 0
            tag_lines = []
            for camera_id, camera in self.cameras.items():
                if not camera.latest:
                    continue
                for tag in camera.latest["tags"]:
                    if tags_shown >= 12:
                        break
                    tag_lines.append(
                        f"{camera_id:<12}{tag['id']:<12}{tag['hamming']:<13}"
                        f"{tag['decision_margin']:.2f}"
                    )
                    tags_shown += 1
            if tag_lines:
                lines += ["", "CAMERA      TAG ID      HAMMING      DECISION MARGIN", *tag_lines]
            if not self.cameras:
                lines.append("Waiting for daemon status...")
            return lines


class Follower(threading.Thread):
    """Read disk independently of terminal rendering, retaining bounded state."""

    def __init__(self, paths: list[Path], state: State):
        super().__init__(daemon=True)
        self.paths, self.state = paths, state
        self.stop_event = threading.Event()

    def run(self) -> None:
        files = [path.open("rb") for path in self.paths]
        buffers = [b"" for _ in files]
        discarding = [False for _ in files]
        try:
            while True:
                read_any = False
                for index, source in enumerate(files):
                    chunk = source.read(65536)
                    if not chunk:
                        continue
                    read_any = True
                    for part_index, part in enumerate(chunk.split(b"\n")):
                        if part_index:
                            if not discarding[index]:
                                self.state.ingest(
                                    buffers[index].decode("utf-8", errors="replace"),
                                    time.monotonic(),
                                    index == 1,
                                )
                            buffers[index], discarding[index] = b"", False
                        if not discarding[index]:
                            buffers[index] += part
                            if len(buffers[index]) > MAX_LINE:
                                self.state.ingest(
                                    "Oversized line omitted from display", time.monotonic(), True
                                )
                                buffers[index], discarding[index] = b"", True
                if not read_any:
                    if self.stop_event.is_set():
                        for index, pending in enumerate(buffers):
                            if pending:
                                self.state.ingest(
                                    pending.decode("utf-8", errors="replace"),
                                    time.monotonic(),
                                    index == 1,
                                )
                        break
                    self.stop_event.wait(0.05)
        finally:
            for source in files:
                source.close()


def remote_command(args) -> str:
    if args.daemon:
        probe = [
            args.remote_python,
            "-u",
            "tools/prototype_daemon.py",
            "--config",
            args.config,
            "--port",
            str(args.stream_port),
        ]
    else:
        probe = [
            args.remote_python,
            "-u",
            "-m",
            "spot_vision",
            "probe",
            "--config",
            args.config,
            "--camera",
            args.camera,
        ]
        if args.frames:
            probe += ["--frames", str(args.frames)]
    return (
        "stty -echo -onlcr && cd -- "
        + shlex.quote(args.remote_dir)
        + " && exec "
        + shlex.join(probe)
    )


def ssh_options(socket: str) -> list[str]:
    return [
        "ssh",
        "-S",
        socket,
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=3",
    ]


def authenticate(host: str, socket: str) -> None:
    # Inherit the real terminal so standard SSH trust/password prompts work.
    subprocess.run(ssh_options(socket) + ["-M", "-o", "ControlPersist=no", "-fN", host], check=True)


def ssh_command(args, socket: str) -> list[str]:
    return ssh_options(socket) + [
        "-o",
        "BatchMode=yes",
        "-o",
        "ControlMaster=no",
        "-tt",
        args.host,
        remote_command(args),
    ]


def service_state(host: str, socket: str) -> str:
    command = ssh_options(socket) + [
        "-o",
        "BatchMode=yes",
        host,
        "systemctl show --property=ActiveState --value spot-vision.service",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True)
    state = result.stdout.strip()
    if state not in {"active", "inactive", "failed"}:
        raise RuntimeError(f"Unexpected spot-vision.service state: {state!r}")
    return state


def service_action(host: str, socket: str, action: str) -> None:
    if action not in {"start", "stop"}:
        raise ValueError(f"Unsupported service action: {action}")
    subprocess.run(
        ssh_options(socket)
        + [
            "-tt",
            host,
            f"sudo systemctl {action} spot-vision.service",
        ],
        check=True,
    )


def prepare_alpha_network(host: str, preferred_interface: str | None = None) -> str | None:
    """Temporarily put a direct Mac Ethernet link on the Jetson's alpha subnet."""
    if sys.platform != "darwin" or host != ALPHA_HOST:
        return None
    target_subnet = ipaddress.ip_network(ALPHA_MAC_ADDRESS, strict=False)
    interface_names = subprocess.run(
        ["ifconfig", "-l"], capture_output=True, text=True, check=True
    ).stdout.split()
    candidates = []
    for interface in interface_names:
        if not re.fullmatch(r"en\d+", interface):
            continue
        output = subprocess.run(
            ["ifconfig", interface], capture_output=True, text=True, check=True
        ).stdout
        addresses = [
            ipaddress.ip_address(address)
            for address in re.findall(r"^\s*inet (\d+\.\d+\.\d+\.\d+)\b", output, re.MULTILINE)
        ]
        if any(address in target_subnet for address in addresses):
            return None
        if "status: active" in output and any(address.is_link_local for address in addresses):
            candidates.append(interface)
    if preferred_interface:
        if preferred_interface not in candidates:
            raise RuntimeError(
                f"{preferred_interface} is not an active, self-assigned Ethernet link"
            )
        interface = preferred_interface
    elif len(candidates) == 1:
        interface = candidates[0]
    else:
        raise RuntimeError(
            "Could not identify one active direct Ethernet link for the Jetson; "
            "connect it and retry, or pass --alpha-interface enX"
        )
    print(
        f"Adding temporary {ALPHA_MAC_ADDRESS} address to {interface} for Jetson access...",
        flush=True,
    )
    subprocess.run(["sudo", "ifconfig", interface, "inet", ALPHA_MAC_ADDRESS, "alias"], check=True)
    return interface


def remove_alpha_network(interface: str) -> None:
    print(f"Removing temporary Jetson address from {interface}...", flush=True)
    subprocess.run(
        ["sudo", "ifconfig", interface, "inet", ALPHA_MAC_ADDRESS.split("/")[0], "-alias"],
        check=True,
    )


def stop_process(process: subprocess.Popen, grace: float = 5) -> None:
    if process.poll() is not None:
        return
    try:
        process.stdin.write(b"\x03")
        process.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def screen_loop(screen, process: subprocess.Popen, state, args, run_dir: Path) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.nodelay(True)
    while process.poll() is None:
        height, width = screen.getmaxyx()
        screen.erase()
        lines = state.lines(
            args.host or "local demo", args.camera or "front", time.monotonic(), "RUNNING"
        )
        if args.alpha:
            lines.insert(
                1,
                f"AdvantageScope NT4: {args.host.rsplit('@', 1)[-1]} | "
                f"Camera viewer: {stream_url(args)}",
            )
        with state.lock:
            events = list(state.events)
        room = max(0, height - len(lines) - 4)
        lines += ["Recent events:"] + (events[-room:] if room else [])
        lines = lines[: max(0, height - 2)]
        target = "daemon and viewer" if args.daemon else "probe"
        lines += [f"Logs: {run_dir}", f"q / Ctrl-C: stop {target} and exit"]
        for row, line in enumerate(lines[:height]):
            try:
                screen.addnstr(row, 0, clean(line), max(0, width - 1))
            except curses.error:
                pass
        screen.refresh()
        if screen.getch() in (ord("q"), 3):
            return
        time.sleep(0.25)


def run_session(
    command: list[str], run_dir: Path, state, display, output_name: str = "probe.log"
) -> int:
    paths = [run_dir / output_name, run_dir / "ssh.log"]
    with paths[0].open("wb") as stdout, paths[1].open("wb") as stderr:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, start_new_session=True
        )
        follower = Follower(paths, state)
        follower.start()
        try:
            display(process)
        finally:
            try:
                stop_process(process)
            finally:
                process.stdin.close()
                follower.stop_event.set()
                follower.join()
        with state.lock:
            state.event(f"Process exited with status {process.returncode}", time.monotonic())
        return process.returncode


def _prototype_record(payload: dict) -> str:
    return json.dumps(
        {
            "time": "demo",
            "level": "DEBUG",
            "logger": "demo",
            "message": payload["type"],
            "prototype": payload,
        },
        separators=(",", ":"),
    )


def emit_demo(frames: int, daemon: bool = False) -> None:
    def receive_stop():
        while True:
            char = os.read(sys.stdin.fileno(), 1)
            if not char or char == b"\x03":
                stop.set()
                return

    stop = threading.Event()
    threading.Thread(target=receive_stop, daemon=True).start()
    if daemon:
        print(_prototype_record({"type": "viewer", "ready": True, "port": 8765}), flush=True)
        camera_ids = ("front", "rear")
        for i in range(frames or 120):
            if stop.wait(0.1):
                break
            if i == 60 and stop.wait(2.5):
                break
            statuses = {}
            for camera_id, capture_fps in zip(camera_ids, (50.0, 120.0)):
                statuses[camera_id] = {
                    "state": "RUNNING",
                    "fps_capture": capture_fps,
                    "fps_detect": 24.0,
                    "capture_failures": 0,
                    "decode_failures": 0,
                    "overwritten_before_processing": i // 35,
                    "result_queue_drops": 0,
                    "driver_sequence_gaps": 0,
                    "error": "",
                }
            if i % 10 == 0:
                print(
                    _prototype_record(
                        {"type": "status", "temperature_c": 48.5, "cameras": statuses}
                    ),
                    flush=True,
                )
            for camera_index, camera_id in enumerate(camera_ids):
                tags = (
                    []
                    if (i + camera_index * 10) % 40 >= 30
                    else [
                        {
                            "id": 8 + camera_index,
                            "hamming": 0,
                            "decision_margin": 100 + i % 9,
                            "corners": [1, 1, 2, 1, 2, 2, 1, 2],
                        }
                    ]
                )
                if i == 20 and camera_id == "front":
                    tags *= 2
                print(
                    _prototype_record(
                        {
                            "type": "frame",
                            "camera_id": camera_id,
                            "sequence": i + 1,
                            "state": "RUNNING" if tags else "NO_TARGETS",
                            "tags": tags,
                            "candidate_count": int(bool(tags)),
                            "capture_fps": statuses[camera_id]["fps_capture"],
                            "detect_fps": 24.0,
                            "timing": {
                                "capture_to_detect_ms": 8.0,
                                "detect_ms": 6.0 + camera_index,
                                "solve_ms": 0.2,
                                "total_ms": 8.5 + camera_index,
                            },
                            "drops": {
                                "capture": 0,
                                "decode": 0,
                                "overwrite": i // 35,
                                "result_queue": 0,
                                "sequence": 0,
                            },
                        }
                    ),
                    flush=True,
                )
        return
    print("Synthetic camera enumeration — no SSH or hardware", flush=True)
    for i in range(frames or 120):
        if stop.wait(0.1):
            break
        # Include disappearance, duplicates, diagnostics and a visible stale interval.
        if i == 60 and stop.wait(2.5):
            break
        tags = (
            []
            if i % 40 >= 30
            else [
                {
                    "id": 8,
                    "hamming": 0,
                    "decision_margin": 100 + i % 9,
                    "corners": [[1, 1], [2, 1], [2, 2], [1, 2]],
                }
            ]
        )
        if i % 40 == 20:
            tags *= 2
        if i == 45:
            print("Synthetic diagnostic: exposure unchanged", file=sys.stderr, flush=True)
        print(
            json.dumps(
                {
                    "sequence": i + 1,
                    "tags": tags,
                    "capture_fps": 50,
                    "detect_ms": 6 + (i % 5) / 10,
                    "total_ms": 6.5 + (i % 7) / 10,
                    "dropped_before_processing": i // 35,
                }
            ),
            flush=True,
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--host")
    result.add_argument("--remote-dir")
    result.add_argument("--camera")
    result.add_argument("--daemon", action="store_true")
    result.add_argument(
        "--alpha", action="store_true", help="run the documented four-camera Jetson alpha session"
    )
    result.add_argument("--alpha-interface", help="Mac Ethernet interface for direct Jetson link")
    result.add_argument("--config", default="config/spot.json")
    result.add_argument("--remote-python")
    result.add_argument("--frames", type=int, default=0)
    result.add_argument("--stream-host")
    result.add_argument("--stream-port", type=int, default=8765)
    result.add_argument("--no-open-browser", action="store_true")
    result.add_argument(
        "--log-dir", type=Path, default=Path(__file__).resolve().parents[1] / "prototype-runs"
    )
    result.add_argument("--demo", action="store_true")
    result.add_argument("--emit-demo", action="store_true", help=argparse.SUPPRESS)
    return result


def stream_url(args) -> str:
    host = args.stream_host or args.host.rsplit("@", 1)[-1]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{args.stream_port}/"


def open_viewer_when_ready(state: DaemonState, url: str, timeout: float = 15.0) -> None:
    if not state.viewer_ready.wait(timeout):
        with state.lock:
            state.event(
                "Viewer did not become ready; open the printed URL manually", time.monotonic()
            )
        return
    try:
        with urllib.request.urlopen(url + "healthz", timeout=2) as response:
            if response.status != 200:
                raise OSError(f"health check returned {response.status}")
        if not webbrowser.open(url):
            raise OSError("browser declined the URL")
        with state.lock:
            state.event(f"Opened alpha dashboard: {url}", time.monotonic())
    except Exception as exc:  # noqa: BLE001 - browser launch is best-effort
        with state.lock:
            state.event(f"Could not open viewer automatically: {exc}; open {url}", time.monotonic())


def main() -> int:
    argument_parser = parser()
    args = argument_parser.parse_args()
    if args.alpha:
        if args.demo:
            argument_parser.error("--alpha cannot be combined with --demo")
        args.daemon = True
        args.host = args.host or ALPHA_HOST
        args.remote_dir = args.remote_dir or "/home/team581/spot-2026"
    elif args.alpha_interface:
        argument_parser.error("--alpha-interface requires --alpha")
    args.remote_python = args.remote_python or (
        ".venv311/bin/python" if args.alpha else ".venv/bin/python"
    )
    if args.frames < 0:
        argument_parser.error("--frames must be nonnegative")
    if not 1 <= args.stream_port <= 65535:
        argument_parser.error("--stream-port must be between 1 and 65535")
    if args.emit_demo:
        emit_demo(args.frames, args.daemon)
        return 0
    if not args.demo and not all((args.host, args.remote_dir)):
        argument_parser.error("--host and --remote-dir are required unless using --demo")
    if not args.daemon and not args.demo and not args.camera:
        argument_parser.error("--camera is required for probe mode")
    if args.daemon and args.frames and not args.demo:
        argument_parser.error("--frames is only available in probe mode")
    if args.host and (args.host.startswith("-") or any(c.isspace() for c in args.host)):
        argument_parser.error("--host must be an SSH destination or configuration alias")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        argument_parser.error("the dashboard requires an interactive terminal; run it in Terminal")
    args.log_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=args.log_dir))
    state = DaemonState() if args.daemon else State()
    terminal_settings = termios.tcgetattr(sys.stdin.fileno())
    exit_code = 1
    restore_service = False
    alpha_interface = None
    try:
        if args.alpha:
            alpha_interface = prepare_alpha_network(args.host, args.alpha_interface)
        with tempfile.TemporaryDirectory(prefix="spot-ssh-", dir="/tmp") as temporary:
            socket = str(Path(temporary) / "control")
            try:
                if args.demo:
                    command = [
                        sys.executable,
                        "-u",
                        str(Path(__file__).resolve()),
                        "--emit-demo",
                        "--frames",
                        str(args.frames),
                    ]
                    if args.daemon:
                        command.append("--daemon")
                else:
                    print(
                        f"Authenticating to {args.host} using your SSH configuration...", flush=True
                    )
                    authenticate(args.host, socket)
                    if args.alpha:
                        prior_state = service_state(args.host, socket)
                        if prior_state == "active":
                            restore_service = True
                            print(
                                "Stopping installed Spot service for alpha camera access...",
                                flush=True,
                            )
                            service_action(args.host, socket, "stop")
                            if service_state(args.host, socket) != "inactive":
                                raise RuntimeError("Installed Spot service did not stop")
                    command = ssh_command(args, socket)
                state.started = time.monotonic()

                def display(child):
                    if args.daemon and not args.demo and not args.no_open_browser:
                        threading.Thread(
                            target=open_viewer_when_ready,
                            args=(state, stream_url(args)),
                            daemon=True,
                        ).start()
                    curses.wrapper(screen_loop, child, state, args, run_dir)

                exit_code = run_session(
                    command, run_dir, state, display, "daemon.log" if args.daemon else "probe.log"
                )
            finally:
                if not args.demo:
                    if restore_service:
                        try:
                            print("Restoring installed Spot service...", flush=True)
                            service_action(args.host, socket, "start")
                            if service_state(args.host, socket) != "active":
                                raise RuntimeError("Installed Spot service did not become active")
                        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                            print(f"Spot service restoration failed: {exc}", file=sys.stderr)
                            exit_code = 1
                    try:
                        subprocess.run(
                            ssh_options(socket) + ["-O", "exit", args.host],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                            check=False,
                        )
                    except (OSError, subprocess.SubprocessError) as exc:
                        print(f"SSH control connection cleanup failed: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        exit_code = 130
    except (OSError, subprocess.SubprocessError, curses.error, RuntimeError) as exc:
        print(f"Dashboard failed: {exc}", file=sys.stderr)
    finally:
        if alpha_interface:
            try:
                remove_alpha_network(alpha_interface)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"Temporary Mac network address cleanup failed: {exc}", file=sys.stderr)
                exit_code = 1
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, terminal_settings)
        mean = state.total_ms / state.count if state.count else 0
        measurement = "Daemon total" if args.daemon else "Probe processing"
        print(
            f"Exited: {exit_code} | Observations: {state.count} | "
            f"Tag-bearing: {state.tagged} | {measurement} mean/max: "
            f"{mean:.2f}/{state.maximum_ms:.2f} ms"
        )
        if args.daemon:
            print(f"Alpha GUI: {stream_url(args) if args.host else 'demo only'}")
        elif state.latest:
            print(f"Final reported overwrites: {state.latest['dropped_before_processing']}")
        if exit_code:
            print("Session ended or connection failed; no automatic reconnect. Last events:")
            for event in list(state.events)[-5:]:
                print(event)
        print(f"Recordings: {run_dir}")
    return exit_code if exit_code >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
