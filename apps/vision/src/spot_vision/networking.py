"""Ethernet addressing through a narrow root socket and NetworkManager checkpoints.

This module also runs standalone in the root-owned network helper. It never
imports application code, executes shell text, or changes Wi-Fi/default routes.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import os
import socket
import subprocess
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

SOCKET = "/run/spot-network.sock"
NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
MAX_MESSAGE = 8192
SAVED_CONNECTION = "Spot Ethernet override"
TRIAL_CONNECTION = "Spot Ethernet trial"


class NetworkError(ValueError):
    pass


def validate_change(values):
    if not isinstance(values, dict) or set(values) != {"mode", "address"}:
        raise NetworkError("Choose an address mode and IPv4 address")
    mode, address = values["mode"], values["address"]
    if mode not in {"automatic", "static"}:
        raise NetworkError("Choose Automatic (DHCP) or Static")
    if not isinstance(address, str) or len(address) > 32:
        raise NetworkError("Use an IPv4 address with a prefix, for example 10.5.81.11/24")
    if mode == "automatic":
        if address:
            raise NetworkError("Automatic mode does not take a static address")
        return dict(values)
    try:
        parsed = ipaddress.IPv4Interface(address)
    except ValueError as exc:
        raise NetworkError("Use an IPv4 address with a prefix, for example 10.5.81.11/24") from exc
    if (
        "/" not in address
        or not 1 <= parsed.network.prefixlen <= 30
        or parsed.ip.is_multicast
        or parsed.ip.is_loopback
        or parsed.ip.is_link_local
        or parsed.ip.is_unspecified
        or parsed.ip.is_reserved
        or parsed.ip in {parsed.network.network_address, parsed.network.broadcast_address}
    ):
        raise NetworkError("Choose a usable IPv4 host address and prefix /1 through /30")
    return {**values, "address": str(parsed)}


def run(arguments, *, timeout=8):
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NetworkError(
            "Network service did not respond; previous settings are protected by rollback"
        ) from exc
    if result.returncode:
        raise NetworkError(result.stderr.strip()[:400] or "Network command failed")
    return result.stdout.strip()


class NetworkManager:
    def __init__(
        self,
        interface: str,
        maintenance_address: str,
        default_connection: str,
        state=Path("/var/lib/spot-network/transaction.json"),
        runner=run,
    ):
        self.interface = interface
        self.maintenance_address = str(ipaddress.IPv4Interface(maintenance_address))
        self.default_connection = default_connection
        self.state, self.run = state, runner

    def nm(self, *args, timeout=8):
        return self.run(["nmcli", *args], timeout=timeout)

    def bus(self, method, signature="", *args):
        reply = self.run(
            [
                "busctl",
                "--system",
                "--json=short",
                "call",
                NM,
                NM_PATH,
                NM,
                method,
                signature,
                *map(str, args),
            ]
        )
        return json.loads(reply)["data"] if reply else []

    def checkpoints(self):
        reply = self.run(
            ["busctl", "--system", "--json=short", "get-property", NM, NM_PATH, NM, "Checkpoints"]
        )
        return json.loads(reply)["data"]

    def rollback(self, checkpoint):
        if checkpoint not in self.checkpoints():
            return
        self.bus("CheckpointRollback", "o", checkpoint)
        if checkpoint in self.checkpoints():
            self.bus("CheckpointDestroy", "o", checkpoint)

    def connections(self):
        return dict(
            row.split(":", 1)
            for row in self.nm("-t", "-f", "UUID,NAME", "connection", "show").splitlines()
            if ":" in row
        )

    def delete_owned(self, identity):
        if identity != self.default_connection and self.connections().get(identity) in {
            SAVED_CONNECTION,
            TRIAL_CONNECTION,
        }:
            self.nm("connection", "delete", "uuid", identity)

    def save(self, pending):
        self.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.state.with_suffix(".next")
        with temporary.open("w") as stream:
            json.dump(pending, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        temporary.replace(self.state)

    def commit(self, pending):
        self.nm(
            "connection",
            "modify",
            "uuid",
            pending["connection_uuid"],
            "connection.id",
            SAVED_CONNECTION,
            "connection.autoconnect",
            "yes",
        )

    def pending(self):
        if not self.state.exists():
            return None
        pending = json.loads(self.state.read_text())
        if pending["checkpoint"] not in self.checkpoints():
            # Reconcile an interrupted confirmation only if its connection is
            # still active. A timed-out trial must never become a boot default.
            if pending.get("confirm_requested") and (
                self.network()["connection_uuid"] == pending["connection_uuid"]
            ):
                self.commit(pending)
                self.delete_owned(pending["previous_connection_uuid"])
            else:
                self.delete_owned(pending["connection_uuid"])
            self.state.unlink()
            return None
        return pending

    def network(self):
        links = json.loads(self.run(["ip", "-json", "address", "show"]))
        link = next((link for link in links if link["ifname"] == self.interface), None)
        if (
            link is None
            or self.nm("-g", "GENERAL.TYPE", "device", "show", self.interface) != "bridge"
        ):
            raise NetworkError("The configured Spot Ethernet bridge is unavailable")
        identity = self.nm("-g", "GENERAL.CON-UUID", "device", "show", self.interface)
        if not identity or identity == "--":
            raise NetworkError("The Spot Ethernet bridge has no active connection")
        method = self.nm("-g", "ipv4.method", "connection", "show", "uuid", identity)
        configured = self.nm("-g", "ipv4.addresses", "connection", "show", "uuid", identity)
        return {
            "connection_uuid": identity,
            "connected": "LOWER_UP" in link.get("flags", []),
            "addresses": [
                f"{a['local']}/{a['prefixlen']}"
                for a in link.get("addr_info", [])
                if a["family"] == "inet"
            ],
            "mode": "automatic" if method == "auto" else "static",
            "address": next(
                (
                    a.strip()
                    for a in configured.split(",")
                    if a.strip() and a.strip() != self.maintenance_address
                ),
                "",
            )
            if method == "manual"
            else "",
        }

    def status(self):
        pending = self.pending()
        network = self.network()
        hostname, discovery = "", "unavailable"
        try:
            reply = self.run(
                [
                    "busctl",
                    "--system",
                    "--json=short",
                    "call",
                    "org.freedesktop.Avahi",
                    "/",
                    "org.freedesktop.Avahi.Server",
                    "GetHostNameFqdn",
                ]
            )
            hostname = json.loads(reply)["data"][0]
            discovery = "active"
        except NetworkError:
            pass
        return {
            "available": True,
            "hostname": hostname,
            "discovery": discovery,
            "maintenance_address": self.maintenance_address,
            "addresses": network["addresses"],
            "local_addresses": [address.split("/", 1)[0] for address in network["addresses"]],
            "connected": network["connected"],
            "mode": network["mode"],
            "address": network["address"],
            "pending": {
                "token": pending["token"],
                "address": pending["address"],
                "remaining_s": max(0, round(pending["deadline"] - time.monotonic())),
            }
            if pending
            else None,
        }

    def require_ready(self, pending):
        network = self.network()
        addresses = network["addresses"]
        ready = (
            pending["address"] in addresses
            if pending["mode"] == "static"
            else any(address != self.maintenance_address for address in addresses)
        )
        if (
            network["connection_uuid"] != pending["connection_uuid"]
            or not network["connected"]
            or self.maintenance_address not in addresses
            or not ready
        ):
            raise NetworkError("Wait for both the maintenance and robot addresses, or revert")

    def apply(self, values):
        values = validate_change(values)
        if self.pending():
            raise NetworkError("Confirm or revert the pending network change first")
        selected = self.network()
        profiles = self.connections()
        previous = selected["connection_uuid"]
        if previous != self.default_connection and profiles.get(previous) != SAVED_CONNECTION:
            raise NetworkError("The active bridge connection is not managed by Spot")
        if self.maintenance_address not in selected["addresses"]:
            raise NetworkError("Restore the NixOS maintenance address before changing settings")
        if values["mode"] == "static":
            address = ipaddress.IPv4Interface(values["address"])
            if address.ip == ipaddress.IPv4Interface(self.maintenance_address).ip:
                raise NetworkError("The maintenance address is fixed by NixOS")
            for link in json.loads(self.run(["ip", "-json", "address", "show"])):
                if link["ifname"] == self.interface:
                    continue
                for a in link.get("addr_info", []):
                    if a["family"] == "inet" and address.network.overlaps(
                        ipaddress.IPv4Network(f"{a['local']}/{a['prefixlen']}", strict=False)
                    ):
                        raise NetworkError("This subnet overlaps another Jetson network")
        for identity, name in profiles.items():
            if name == TRIAL_CONNECTION:
                self.delete_owned(identity)
        identity, checkpoint = None, None
        try:
            # Clone only the Nix-owned template, including bridge/MAC/STP policy.
            # The trial stays in memory until the operator confirms it.
            self.nm(
                "connection",
                "clone",
                "--temporary",
                "uuid",
                self.default_connection,
                TRIAL_CONNECTION,
            )
            identity = self.nm("-g", "connection.uuid", "connection", "show", TRIAL_CONNECTION)
            addresses = [self.maintenance_address]
            if values["mode"] == "static":
                addresses.append(values["address"])
            self.nm(
                "connection",
                "modify",
                "--temporary",
                "uuid",
                identity,
                "connection.autoconnect",
                "no",
                "connection.autoconnect-priority",
                "100",
                "ipv4.method",
                "auto" if values["mode"] == "automatic" else "manual",
                "ipv4.addresses",
                ",".join(addresses),
            )
            device = self.nm("-g", "GENERAL.DBUS-PATH", "device", "show", self.interface)
            checkpoint_at = time.monotonic()
            checkpoint = self.bus("CheckpointCreate", "aouu", 1, device, 90, 0)[0]
            pending = {
                **values,
                "token": uuid.uuid4().hex,
                "connection_uuid": identity,
                "previous_connection_uuid": previous,
                "checkpoint": checkpoint,
                "deadline": checkpoint_at + 90,
            }
            self.save(pending)
            self.nm("--wait", "45", "connection", "up", "uuid", identity, timeout=49)
        except Exception:
            if checkpoint:
                self.rollback(checkpoint)
            if identity:
                self.delete_owned(identity)
            self.state.unlink(missing_ok=True)
            raise
        return self.status()

    def finish(self, token, *, keep):
        pending = self.pending()
        if not pending or token != pending["token"]:
            raise NetworkError("This network change expired or was already reverted")
        if keep:
            self.require_ready(pending)
            self.bus("CheckpointAdjustRollbackTimeout", "ou", pending["checkpoint"], 30)
            pending["deadline"] = time.monotonic() + 30
            pending["confirm_requested"] = True
            self.save(pending)
            self.commit(pending)
            self.bus("CheckpointDestroy", "o", pending["checkpoint"])
            self.delete_owned(pending["previous_connection_uuid"])
        else:
            self.rollback(pending["checkpoint"])
            self.delete_owned(pending["connection_uuid"])
        self.state.unlink(missing_ok=True)
        return self.status()

    def handle(self, request):
        if not isinstance(request, dict) or set(request) != {"operation", "payload"}:
            raise NetworkError("Invalid network request")
        op, payload = request["operation"], request["payload"]
        if op == "status" and payload == {}:
            return self.status()
        if op == "apply":
            return self.apply(payload)
        if op in {"confirm", "revert"} and isinstance(payload, dict) and set(payload) == {"token"}:
            return self.finish(payload["token"], keep=op == "confirm")
        raise NetworkError("Unknown network operation")


class NetworkClient:
    def __init__(self, path=SOCKET):
        self.path, self.stop = path, threading.Event()
        self.snapshot = {"available": False, "error": "Network helper is not installed"}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="network-change")
        self.busy = threading.Lock()
        self.worker = threading.Thread(target=self._poll, name="network-status", daemon=True)

    def request(self, operation, payload):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(60)
            connection.connect(self.path)
            connection.sendall(
                (json.dumps({"operation": operation, "payload": payload}) + "\n").encode()
            )
            with connection.makefile("rb") as stream:
                reply = json.loads(stream.readline(65537))
        if "error" in reply:
            raise NetworkError(reply["error"])
        self.snapshot = reply["result"]
        return copy.deepcopy(self.snapshot)

    def _poll(self):
        while not self.stop.is_set():
            try:
                self.request("status", {})
            except (OSError, ValueError) as exc:
                self.snapshot = {
                    "available": False,
                    "error": "Network helper unavailable: " + str(exc)[:180],
                }
            self.stop.wait(3)

    def submit(self, operation, payload, guard=lambda: None):
        if not self.busy.acquire(blocking=False):
            future = Future()
            future.set_exception(NetworkError("Network change already in progress"))
            return future

        def execute():
            try:
                guard()
                result = self.request(operation, payload)
                return {"result": result}
            finally:
                self.busy.release()

        return self.executor.submit(execute)

    def close(self):
        self.stop.set()
        self.executor.shutdown(wait=False, cancel_futures=True)


def serve():
    if os.geteuid() != 0 or os.environ.get("LISTEN_FDS") != "1":
        raise SystemExit("Run through spot-network.socket")
    listener = socket.socket(fileno=3)
    manager = NetworkManager(**json.loads(Path("/etc/spot-vision/network.json").read_text()))
    while True:
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(5)
            try:
                with connection.makefile("rb") as stream:
                    raw = stream.readline(MAX_MESSAGE + 1)
                if len(raw) > MAX_MESSAGE or not raw.endswith(b"\n"):
                    raise NetworkError("Network request is too large")
                reply = {"result": manager.handle(json.loads(raw))}
            except Exception as exc:
                reply = {"error": str(exc)[:500]}
            try:
                connection.sendall((json.dumps(reply) + "\n").encode())
            except OSError:
                pass


if __name__ == "__main__":
    serve()
