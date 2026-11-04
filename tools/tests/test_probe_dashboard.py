from __future__ import annotations

import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "probe_dashboard.py"
spec = importlib.util.spec_from_file_location("probe_dashboard", SCRIPT)
dashboard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dashboard
spec.loader.exec_module(dashboard)


def record(sequence=1, tags=None, total=7):
    return {
        "sequence": sequence,
        "tags": [] if tags is None else tags,
        "capture_fps": 50,
        "detect_ms": 6,
        "total_ms": total,
        "dropped_before_processing": 2,
    }


def prototype(payload):
    return json.dumps({"message": payload["type"], "prototype": payload})


def test_parsing_events_statistics_and_freshness():
    state = dashboard.State(started=0)
    tag = {"id": 8, "hamming": 0, "decision_margin": 105}
    state.ingest("camera startup\x1b[31m", 0)
    state.ingest("{broken", 0)
    state.ingest(json.dumps(record(2, [tag, tag], 6)), 1)
    assert len(state.latest["tags"]) == 2
    assert sum("appeared" in event for event in state.events) == 1
    state.ingest(json.dumps(record(1, total=10)), 2)
    assert state.count == 2 and state.tagged == 1 and state.total_ms == 16
    assert any("Sequence reset" in event for event in state.events)
    assert any("disappeared" in event for event in state.events)
    assert "No tags in latest result" in state.lines("host", "front", 2, "RUNNING")
    assert any("8.00 / 9.80 ms" in line for line in state.lines("host", "front", 2, "RUNNING"))
    assert any("STALE" in line for line in state.lines("host", "front", 4, "RUNNING"))
    state.lines("host", "front", 10, "RUNNING")
    assert not state.samples
    assert "\x1b" not in "".join(state.events)
    assert "Waiting for first result" in dashboard.State(started=0).lines("h", "c", 0, "RUNNING")


@pytest.mark.parametrize(
    "bad",
    [
        {"sequence": 1},
        [],
        dict(record(), detect_ms=float("nan")),
        dict(record(), tags=[{"id": 8}]),
        dict(record(), total_ms=-1),
    ],
)
def test_invalid_records_do_not_crash(bad):
    state = dashboard.State()
    state.ingest(json.dumps(bad), time.monotonic())
    assert state.count == 0


def test_bounded_history():
    state = dashboard.State(started=0)
    for index in range(5100):
        state.ingest(json.dumps(record(index)), index / 10000)
        state.ingest("diagnostic", index / 10000)
    assert len(state.samples) == 5000
    assert len(state.events) == 20
    assert state.count == 5100


def test_follower_partial_lines_and_oversize(tmp_path):
    paths = [tmp_path / "probe.log", tmp_path / "ssh.log"]
    for path in paths:
        path.touch()
    state = dashboard.State()
    follower = dashboard.Follower(paths, state)
    follower.start()
    encoded = json.dumps(record()).encode()
    with paths[0].open("ab", buffering=0) as output:
        output.write(b"camera modes\n" + encoded[:10])
        time.sleep(0.1)
        assert state.count == 0
        output.write(encoded[10:] + b"\n")
        output.write(b"x" * (dashboard.MAX_LINE + 1) + b"\n")
        output.write(json.dumps(record(2)).encode())  # final line without newline
    paths[1].write_text("connection diagnostic\n")
    follower.stop_event.set()
    follower.join(timeout=3)
    assert not follower.is_alive()
    assert state.count == 2
    assert any("Oversized" in event for event in state.events)
    assert any("connection diagnostic" in event for event in state.events)


def test_remote_arguments_are_shell_quoted():
    args = dashboard.parser().parse_args(
        [
            "--host",
            "my-alias",
            "--remote-dir",
            "/tmp/with spaces;$(touch bad)'",
            "--remote-python",
            "/tmp/python with spaces",
            "--camera",
            "front;echo bad",
            "--config",
            "/tmp/a `bad`.json",
            "--frames",
            "3",
        ]
    )
    tokens = shlex.split(dashboard.remote_command(args))
    assert tokens[:5] == ["stty", "-echo", "-onlcr", "&&", "cd"]
    assert tokens[5] == "--"
    assert tokens[6] == args.remote_dir
    assert tokens[9] == args.remote_python
    assert tokens[tokens.index("--camera") + 1] == args.camera
    assert tokens[tokens.index("--config") + 1] == args.config
    command = dashboard.ssh_command(args, "/tmp/socket")
    assert "-tt" in command and "BatchMode=yes" in command
    assert command[-2] == "my-alias"


@pytest.fixture
def fake_ssh(tmp_path):
    executable = tmp_path / "ssh"
    executable.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """
import json, sys, time
mode = sys.argv[-1]
print('fake camera enumeration', flush=True)
print(json.dumps(dict(sequence=1, tags=[], capture_fps=50, detect_ms=6,
                      total_ms=7, dropped_before_processing=0)), flush=True)
if mode == 'failure':
    print('Connection lost', file=sys.stderr, flush=True)
    sys.exit(255)
if mode == 'stop':
    assert sys.stdin.buffer.read(1) == b'\\x03'
    print('remote stopped', flush=True)
elif mode == 'hang':
    time.sleep(30)
else:
    for i in range(1000):
        print('diagnostic ' + str(i), flush=True)
"""
    )
    executable.chmod(0o755)
    return executable


@pytest.mark.parametrize("mode, expected", [("failure", 255), ("stop", 0), ("burst", 0)])
def test_fake_ssh_recording_lifecycle(fake_ssh, tmp_path, mode, expected):
    state = dashboard.State()

    def display(process):
        if mode == "stop":
            time.sleep(0.15)
        else:
            process.wait(timeout=3)  # no rendering; child must continue

    result = dashboard.run_session([str(fake_ssh), "-tt", mode], tmp_path, state, display)
    assert result == expected
    assert state.count == 1
    assert "fake camera enumeration" in (tmp_path / "probe.log").read_text()
    if mode == "failure":
        assert "Connection lost" in (tmp_path / "ssh.log").read_text()
    if mode == "stop":
        assert "remote stopped" in (tmp_path / "probe.log").read_text()
    if mode == "burst":
        assert "diagnostic 999" in (tmp_path / "probe.log").read_text()


def test_shutdown_escalation(fake_ssh):
    process = subprocess.Popen(
        [str(fake_ssh), "hang"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        dashboard.stop_process(process, grace=0.05)
        assert process.poll() is not None
    finally:
        process.stdin.close()
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.parametrize("exit_mode", ["q", "interrupt", "complete"])
def test_demo_terminal_resize_and_restore(tmp_path, exit_mode):
    import fcntl
    import pty
    import select
    import signal
    import struct
    import termios

    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--demo", "--frames", "12", "--log-dir", str(tmp_path)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=dict(os.environ, TERM="xterm-256color"),
        start_new_session=True,
    )
    captured = bytearray()
    try:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                captured.extend(os.read(master, 65536))
            if b"Detector" in captured:
                break
        assert b"Spot prototype" in captured and b"Detector" in captured
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 8, 35, 0, 0))
        process.send_signal(signal.SIGWINCH)
        time.sleep(0.3)
        if exit_mode == "q":
            os.write(master, b"q")
        elif exit_mode == "interrupt":
            process.send_signal(signal.SIGINT)
        # Drain the PTY while waiting so test output cannot block termination.
        deadline = time.monotonic() + 7
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                captured.extend(os.read(master, 65536))
        assert process.wait(timeout=1) == (130 if exit_mode == "interrupt" else 0)
        after = termios.tcgetattr(slave)
        # macOS may set the transient pending-input-retype flag after cooked-mode restore.
        after[3] &= ~getattr(termios, "PENDIN", 0)
        before[3] &= ~getattr(termios, "PENDIN", 0)
        assert after == before
        assert list(tmp_path.glob("*/probe.log"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)


def test_redirected_output_has_clear_error():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--demo"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "interactive terminal" in result.stderr


def test_authentication_preserves_normal_ssh_prompts(monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    dashboard.authenticate("existing-alias", "/tmp/private-control")
    command = calls[0][0][0]
    assert command[-1] == "existing-alias"
    assert "-M" in command and "-fN" in command
    assert not any("StrictHostKeyChecking" in arg or "BatchMode" in arg for arg in command)
    assert calls[0][1] == {"check": True}


def test_alpha_network_adds_and_removes_temporary_mac_address(monkeypatch):
    calls = []
    outputs = {
        ("ifconfig", "-l"): "en0 en8",
        ("ifconfig", "en0"): "inet 192.168.1.228 netmask 0xffffff00\nstatus: active",
        ("ifconfig", "en8"): "inet 169.254.139.126 netmask 0xffff0000\nstatus: active",
    }

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, outputs.get(tuple(command), ""))

    monkeypatch.setattr(dashboard.sys, "platform", "darwin")
    monkeypatch.setattr(dashboard.subprocess, "run", run)
    interface = dashboard.prepare_alpha_network(dashboard.ALPHA_HOST)
    assert interface == "en8"
    assert ["sudo", "ifconfig", "en8", "inet", "192.168.69.171/24", "alias"] in calls
    dashboard.remove_alpha_network(interface)
    assert calls[-1] == ["sudo", "ifconfig", "en8", "inet", "192.168.69.171", "-alias"]


def test_alpha_network_leaves_existing_jetson_subnet_alone(monkeypatch):
    commands = []
    outputs = {
        ("ifconfig", "-l"): "en0 en8",
        ("ifconfig", "en0"): "inet 192.168.1.228\nstatus: active",
        ("ifconfig", "en8"): "inet 192.168.69.171\nstatus: active",
    }

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, outputs[tuple(command)])

    monkeypatch.setattr(dashboard.sys, "platform", "darwin")
    monkeypatch.setattr(dashboard.subprocess, "run", run)
    assert dashboard.prepare_alpha_network(dashboard.ALPHA_HOST) is None
    assert not any(command[0] == "sudo" for command in commands)


def test_huge_numeric_value_is_rejected():
    state = dashboard.State()
    state.ingest(json.dumps(dict(record(), total_ms=10**400)), time.monotonic())
    assert state.count == 0


def test_daemon_state_discovers_cameras_and_tracks_frames_independently():
    state = dashboard.DaemonState(started=0)
    status = {
        "type": "status",
        "temperature_c": 47.5,
        "cameras": {
            "front": {
                "state": "RUNNING",
                "fps_capture": 50,
                "fps_detect": 24,
                "capture_failures": 0,
                "decode_failures": 0,
                "overwritten_before_processing": 2,
                "result_queue_drops": 0,
                "driver_sequence_gaps": 0,
                "error": "",
            },
            "rear": {
                "state": "RETRY_WAIT",
                "fps_capture": 0,
                "fps_detect": 0,
                "capture_failures": 1,
                "decode_failures": 0,
                "overwritten_before_processing": 0,
                "result_queue_drops": 0,
                "driver_sequence_gaps": 0,
                "error": "camera missing",
            },
        },
    }
    state.ingest(prototype(status), 1)
    tag = {"id": 8, "hamming": 0, "decision_margin": 105, "corners": []}
    frame = {
        "type": "frame",
        "camera_id": "front",
        "sequence": 2,
        "state": "RUNNING",
        "tags": [tag, tag],
        "candidate_count": 1,
        "capture_fps": 50,
        "detect_fps": 24,
        "timing": {"detect_ms": 6, "total_ms": 8},
        "drops": {"capture": 0, "decode": 0, "overwrite": 2, "result_queue": 0, "sequence": 0},
    }
    state.ingest(prototype(frame), 1.5)
    lines = state.lines("orin-1", "", 1.5, "RUNNING")
    assert state.count == 1 and state.tagged == 1
    assert set(state.cameras) == {"front", "rear"}
    assert sum("tag 8 appeared" in event for event in state.events) == 1
    assert any("front" in line and "8,8" in line for line in lines)
    assert any("rear" in line and "RETRY" in line for line in lines)
    assert any("47.5 C" in line for line in lines)
    assert any("stale" in line for line in state.lines("orin-1", "", 4, "RUNNING"))


def test_daemon_viewer_record_and_invalid_record_are_safe():
    state = dashboard.DaemonState(started=0)
    state.ingest(prototype({"type": "viewer", "ready": True, "port": 8765}), 1)
    assert state.viewer_ready.is_set()
    assert "8765" in state.viewer_status
    state.ingest("{bad", 2)
    state.ingest(prototype({"type": "frame", "camera_id": "front"}), 2)
    assert state.count == 0
    assert state.events


def test_daemon_remote_command_and_stream_url_are_quoted():
    args = dashboard.parser().parse_args(
        [
            "--daemon",
            "--host",
            "user@192.0.2.5",
            "--remote-dir",
            "/tmp/with spaces",
            "--config",
            "/tmp/a config.json",
            "--stream-port",
            "9000",
        ]
    )
    tokens = shlex.split(dashboard.remote_command(args))
    assert "tools/prototype_daemon.py" in tokens
    assert tokens[tokens.index("--config") + 1] == "/tmp/a config.json"
    assert tokens[tokens.index("--port") + 1] == "9000"
    assert "--camera" not in tokens
    assert dashboard.stream_url(args) == "http://192.0.2.5:9000/"
    args.stream_host = "2001:db8::1"
    assert dashboard.stream_url(args) == "http://[2001:db8::1]:9000/"
    args.alpha = True
    tokens = shlex.split(dashboard.remote_command(args))
    assert "--rotate-preview" not in tokens


@pytest.fixture
def alpha_ssh(tmp_path):
    executable = tmp_path / "ssh"
    executable.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """
import os, pathlib, sys
state = pathlib.Path(os.environ['SPOT_FAKE_STATE'])
calls = pathlib.Path(os.environ['SPOT_FAKE_CALLS'])
command = sys.argv[-1]
with calls.open('a') as log:
    log.write(command + '\\n')
if '-fN' in sys.argv or command == 'exit':
    sys.exit(0)
if command.startswith('systemctl show'):
    print(state.read_text().strip())
elif command == 'sudo systemctl stop spot-vision.service':
    if os.environ.get('SPOT_FAKE_STOP_FAIL'):
        sys.exit(1)
    state.write_text('inactive')
elif command == 'sudo systemctl start spot-vision.service':
    state.write_text('active')
elif 'prototype_daemon.py' in command:
    if os.environ.get('SPOT_FAKE_LAUNCH_FAIL'):
        sys.exit(2)
    print('fake alpha daemon', flush=True)
    while True:
        character = sys.stdin.buffer.read(1)
        if not character or character == b'\\x03':
            break
else:
    sys.exit(2)
"""
    )
    executable.chmod(0o755)
    return executable


@pytest.mark.parametrize(
    "initial,exit_mode,stop_fails,expected_calls",
    [
        (
            "active",
            "q",
            False,
            ["sudo systemctl stop", "prototype_daemon.py", "sudo systemctl start"],
        ),
        ("inactive", "q", False, ["prototype_daemon.py"]),
        (
            "active",
            "interrupt",
            False,
            ["sudo systemctl stop", "prototype_daemon.py", "sudo systemctl start"],
        ),
        ("active", "failure", True, ["sudo systemctl stop", "sudo systemctl start"]),
        (
            "active",
            "launch_failure",
            False,
            ["sudo systemctl stop", "prototype_daemon.py", "sudo systemctl start"],
        ),
    ],
)
def test_alpha_service_lifecycle(
    alpha_ssh, tmp_path, initial, exit_mode, stop_fails, expected_calls
):
    import fcntl
    import pty
    import select
    import struct
    import termios

    state = tmp_path / "state"
    state.write_text(initial)
    calls = tmp_path / "calls"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    environment = dict(
        os.environ,
        PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
        TERM="xterm-256color",
        SPOT_FAKE_STATE=str(state),
        SPOT_FAKE_CALLS=str(calls),
    )
    if stop_fails:
        environment["SPOT_FAKE_STOP_FAIL"] = "1"
    if exit_mode == "launch_failure":
        environment["SPOT_FAKE_LAUNCH_FAIL"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--alpha",
            "--host",
            "team581@192.0.2.5",
            "--no-open-browser",
            "--log-dir",
            str(tmp_path / "runs"),
        ],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=environment,
        start_new_session=True,
    )
    captured = bytearray()
    requested_exit = exit_mode
    try:
        deadline = time.monotonic() + 8
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                captured.extend(os.read(master, 65536))
            logs = list((tmp_path / "runs").glob("*/daemon.log"))
            if (
                exit_mode in {"q", "interrupt"}
                and logs
                and b"fake alpha daemon" in logs[0].read_bytes()
            ):
                if exit_mode == "interrupt":
                    process.send_signal(signal.SIGINT)
                else:
                    os.write(master, b"q")
                exit_mode = "sent"
        expected_exit = {"interrupt": 130, "failure": 1, "launch_failure": 2}.get(requested_exit, 0)
        assert process.wait(timeout=2) == expected_exit
        assert state.read_text() == initial
        call_text = calls.read_text()
        for call in expected_calls:
            assert call in call_text
        if stop_fails:
            assert "prototype_daemon.py" not in call_text
        elif not stop_fails:
            assert list((tmp_path / "runs").glob("*/daemon.log"))
            assert b"AdvantageScope NT4" in captured
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)


def test_browser_open_is_best_effort(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    state = dashboard.DaemonState()
    state.viewer_ready.set()
    opened = []
    monkeypatch.setattr(dashboard.urllib.request, "urlopen", lambda *_a, **_k: Response())
    monkeypatch.setattr(dashboard.webbrowser, "open", lambda url: opened.append(url) or True)
    dashboard.open_viewer_when_ready(state, "http://example:8765/", 0.01)
    assert opened == ["http://example:8765/"]
    monkeypatch.setattr(dashboard.webbrowser, "open", lambda _url: False)
    dashboard.open_viewer_when_ready(state, "http://example:8765/", 0.01)
    assert any("Could not open" in event for event in state.events)


def test_daemon_demo_renders_and_records(tmp_path):
    import fcntl
    import pty
    import select
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    process = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--daemon",
            "--demo",
            "--frames",
            "8",
            "--log-dir",
            str(tmp_path),
        ],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=dict(os.environ, TERM="xterm-256color"),
        start_new_session=True,
    )
    captured = bytearray()
    try:
        deadline = time.monotonic() + 5
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                captured.extend(os.read(master, 65536))
        assert process.wait(timeout=1) == 0
        assert b"Spot daemon prototype" in captured
        assert b"front" in captured and b"rear" in captured
        assert list(tmp_path.glob("*/daemon.log"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)
