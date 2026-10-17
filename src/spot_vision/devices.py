"""Physical UVC discovery and capability data, independent of logical names."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .camera_controls import CONTROL_INFO, EXPOSURE_NAMES, HEADER
from .config import ConfigError
from .persistence import canonical_bytes, durable_replace


@dataclass(frozen=True)
class DeviceNode:
    path: str
    topology: str
    vendor: str
    product: str
    serial: str
    label: str
    capture: bool


@dataclass(frozen=True)
class PhysicalDevice:
    identity: str
    display_id: str
    topology: str
    vendor: str
    product: str
    serial: str
    unique_serial: bool
    label: str
    nodes: tuple[str, ...]
    capture_node: str | None
    modes: tuple[dict, ...] = ()
    controls: tuple[dict, ...] = ()
    fault: str = ""


def parse_modes(output: str) -> list[dict]:
    modes = []
    pixel_format = None
    size = None
    for line in output.splitlines():
        match = re.search(r"\[\d+\]:\s*'([A-Z0-9]{4})'", line)
        if match:
            pixel_format, size = match[1], None
        match = re.search(r"Size: Discrete (\d+)x(\d+)", line)
        if match:
            size = int(match[1]), int(match[2])
        match = re.search(r"Interval: Discrete .*\(([0-9.]+) fps\)", line)
        if match and pixel_format and size:
            mode = {
                "pixel_format": pixel_format,
                "width": size[0],
                "height": size[1],
                "fps": float(match[1]),
                "verified": False,
            }
            if mode not in modes:
                modes.append(mode)
    return modes[:256]


def parse_capability_controls(output: str) -> list[dict]:
    """Expose advertised controls, including optional unfamiliar UVC controls.

    Robot policy and the configuration service decide which can be changed.
    Discovery never writes hardware or infers control ranges from product names.
    """
    controls: list[dict] = []
    current = None
    for line in output.splitlines():
        match = HEADER.match(line)
        if match:
            name, kind, attributes = match.groups()
            current = None
            if kind not in {"int", "bool", "menu", "intmenu"}:
                continue
            numbers = {
                key: int(value)
                for key, value in re.findall(r"(min|max|step|default|value)=(-?\d+)", attributes)
            }
            if "value" not in numbers:
                continue
            flags = attributes.split("flags=", 1)[1].strip() if "flags=" in attributes else ""
            current = {
                "name": name,
                "type": kind,
                "label": CONTROL_INFO.get(name, (name.replace("_", " "), ""))[0],
                "min": numbers.get("min", 0),
                "max": numbers.get("max", 1),
                "step": numbers.get("step", 1),
                "default": numbers.get("default"),
                "value": numbers["value"],
                "flags": flags,
                "options": [],
                "writable": not any(
                    flag in flags for flag in ("inactive", "read-only", "disabled", "grabbed")
                ),
                "factor": 100 if name in EXPOSURE_NAMES else 1,
                "unit": "µs" if name in EXPOSURE_NAMES else "",
            }
            controls.append(current)
        elif current is not None:
            option = re.match(r"^\s+(-?\d+):\s*(.+)$", line)
            if option and current["type"] in {"menu", "intmenu"}:
                current["options"].append({"value": int(option[1]), "label": option[2]})
    return controls[:128]


def _run(arguments: list[str], timeout: float = 2.0) -> str:
    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(f"device discovery unavailable: {exc}") from exc
    if result.returncode:
        raise ConfigError(result.stderr.strip() or "device discovery command failed")
    return result.stdout


def enumerate_nodes(progress=lambda: None) -> list[DeviceNode]:
    result = []
    for device in sorted(Path("/dev").glob("video*"))[:128]:
        progress()
        try:
            output = _run(["udevadm", "info", "--query=property", f"--name={device}"])
        except ConfigError:
            continue  # A vanished node cannot take unrelated cameras offline.
        properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        topology = re.sub(r":\d+\.\d+$", "", properties.get("ID_PATH", ""))
        if not topology:
            # No unstable /dev/videoN identity fallback. Discovery may report
            # the failure but cannot silently name/bind this device.
            continue
        result.append(
            DeviceNode(
                str(device),
                topology,
                properties.get("ID_VENDOR_ID", ""),
                properties.get("ID_MODEL_ID", ""),
                properties.get("ID_SERIAL_SHORT", ""),
                properties.get("ID_V4L_PRODUCT", properties.get("ID_MODEL", "USB camera")),
                ":capture:" in properties.get("ID_V4L_CAPABILITIES", ""),
            )
        )
    return result


class DeviceRegistry:
    """Persistent USB port slots, device identities and duplicate-serial knowledge.

    Inventory bookkeeping is separate from optical runtime generations; finding
    a new unused USB camera does not invalidate healthy production measurements.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "devices.json"
        self._lock = threading.RLock()
        self.fault = ""
        self.data = {"schema_version": 1, "display_ids": {}, "duplicate_serials": [], "next_id": 1}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_bytes())
                if (
                    raw["schema_version"] != 1
                    or not isinstance(raw["display_ids"], dict)
                    or not isinstance(raw["duplicate_serials"], list)
                    or len(raw["display_ids"]) > 4096
                    or type(raw["next_id"]) is not int
                    or raw["next_id"] < 1
                ):
                    raise ValueError("invalid registry schema")
                slots = raw.get("port_slots", {})
                if not isinstance(slots, dict) or len(slots) > 4096:
                    raise ValueError("invalid port registry")
                labels = set()
                identities = set()
                for topology, slot in slots.items():
                    if (
                        not isinstance(topology, str) or not topology
                        or not isinstance(slot, dict)
                        or set(slot) != {"display_id", "identities"}
                        or not isinstance(slot["display_id"], str)
                        or slot["display_id"] in labels
                        or not isinstance(slot["identities"], dict)
                        or len(slot["identities"]) > 4096
                        or any(not isinstance(key, str) or not isinstance(value, str)
                               or not re.fullmatch(r"[a-f0-9]{64}", value)
                               for key, value in slot["identities"].items())
                    ):
                        raise ValueError("invalid saved USB port slot")
                    values = set(slot["identities"].values())
                    if len(values) != len(slot["identities"]) or values & identities:
                        raise ValueError("camera identity belongs to multiple USB slots")
                    identities.update(values)
                    labels.add(slot["display_id"])
                self.data = raw
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.fault = f"Device registry corrupt: {exc}"

    def identify(self, nodes: list[DeviceNode]) -> list[PhysicalDevice]:
        grouped: dict[str, list[DeviceNode]] = {}
        for node in nodes:
            grouped.setdefault(node.topology, []).append(node)
        serials = Counter(
            (group[0].vendor, group[0].product, group[0].serial)
            for group in grouped.values()
            if group[0].serial
        )
        with self._lock:
            original = canonical_bytes(self.data)
            duplicates = set(self.data["duplicate_serials"])
            duplicates.update(":".join(key) for key, count in serials.items() if count > 1)
            self.data["duplicate_serials"] = sorted(duplicates)
            slots = self.data.setdefault("port_slots", {})
            devices = []
            for topology, group in grouped.items():
                node = group[0]
                serial_key = f"{node.vendor}:{node.product}:{node.serial}"
                unique = bool(node.serial and serial_key not in duplicates)
                observable = (
                    "serial:" + serial_key
                    if unique
                    else f"port:{node.vendor}:{node.product}:{topology}"
                )
                legacy_identity = hashlib.sha256(observable.encode()).hexdigest()
                used_identities = {identity for slot in slots.values()
                                   for identity in slot["identities"].values()}
                if topology not in slots:
                    if len(slots) >= 4096:
                        raise ConfigError("USB port inventory limit reached")
                    # Adopt an existing installation's identity at its current
                    # port, preserving saved tuning, bindings and calibration.
                    label = self.data["display_ids"].get(legacy_identity)
                    if label is None or label in {slot["display_id"] for slot in slots.values()}:
                        label = f"USB-{self.data['next_id']:02X}"
                        self.data["next_id"] += 1
                    slots[topology] = {"display_id": label, "identities": {}}
                slot = slots[topology]
                identity = slot["identities"].get(observable)
                if identity is None:
                    if len(self.data["display_ids"]) >= 4096:
                        raise ConfigError("device inventory limit reached")
                    identity = legacy_identity if legacy_identity not in used_identities else (
                        hashlib.sha256(f"slot:{topology}:{observable}".encode()).hexdigest()
                    )
                    slot["identities"][observable] = identity
                    self.data["display_ids"][identity] = slot["display_id"]
                capture = sorted(item.path for item in group if item.capture)
                devices.append(
                    PhysicalDevice(
                        identity,
                        slot["display_id"],
                        topology,
                        node.vendor,
                        node.product,
                        node.serial,
                        unique,
                        node.label,
                        tuple(sorted(item.path for item in group)),
                        capture[0] if capture else None,
                        fault="No capture node" if not capture else "",
                    )
                )
            if canonical_bytes(self.data) != original:
                if self.path.exists():
                    durable_replace(self.root / "devices.previous.json", self.path.read_bytes())
                durable_replace(self.path, canonical_bytes(self.data))
            return sorted(devices, key=lambda item: item.display_id)


class DeviceManager:
    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        enumerate_fn: Callable[[], list[DeviceNode]] = enumerate_nodes,
        capability_fn: Callable[[str], str] | None = None,
    ) -> None:
        self.registry = registry
        self._enumerate = enumerate_fn
        self._capabilities = capability_fn or (
            lambda path: _run(
                ["v4l2-ctl", "--device", path, "--all", "--list-formats-ext", "--list-ctrls-menus"]
            )
        )
        self._lock = threading.RLock()
        self._devices: dict[str, PhysicalDevice] = {}
        self.last_progress = time.monotonic()
        self.fault = ""

    def _mark_progress(self):
        self.last_progress = time.monotonic()

    def refresh(self) -> None:
        from dataclasses import replace

        self.last_progress = time.monotonic()
        try:
            devices = self.registry.identify(
                self._enumerate(progress=self._mark_progress)
                if self._enumerate is enumerate_nodes
                else self._enumerate()
            )
            result = {}
            for device in devices[:32]:
                self.last_progress = time.monotonic()
                previous = self._devices.get(device.identity)
                if previous and previous.capture_node == device.capture_node:
                    # Advertised capabilities are static for one continuous
                    # presence; readback refresh belongs to camera controls.
                    result[device.identity] = previous
                    continue
                try:
                    output = self._capabilities(device.capture_node) if device.capture_node else ""
                    device = replace(
                        device,
                        modes=tuple(parse_modes(output)),
                        controls=tuple(parse_capability_controls(output)),
                    )
                except ConfigError as exc:
                    device = replace(device, fault=str(exc))
                result[device.identity] = device
            self.last_progress = time.monotonic()
            with self._lock:
                self._devices = result
                self.fault = self.registry.fault
        except ConfigError as exc:
            with self._lock:
                self.fault = str(exc)
                self._devices = {}  # never retain a stale connected identity

    def get(self, identity: str) -> PhysicalDevice | None:
        with self._lock:
            return self._devices.get(identity)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy([asdict(device) for device in self._devices.values()])
