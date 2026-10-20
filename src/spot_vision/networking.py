"""Ethernet addressing through a narrow root socket and NetworkManager checkpoints.

This module also runs standalone in the root-owned network helper. It never
imports application code, executes shell text, or changes Wi-Fi/default routes.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import os
import re
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


class NetworkError(ValueError):
    pass


def validate_change(values):
    if not isinstance(values, dict) or set(values) != {"interface", "mode", "address"}:
        raise NetworkError("Choose an Ethernet port, address mode and IPv4 address")
    interface, mode, address = (values[k] for k in ("interface", "mode", "address"))
    if not isinstance(interface, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", interface):
        raise NetworkError("Invalid Ethernet port")
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
    if ("/" not in address or not 1 <= parsed.network.prefixlen <= 30
            or parsed.ip.is_multicast or parsed.ip.is_loopback or parsed.ip.is_link_local
            or parsed.ip.is_unspecified or parsed.ip.is_reserved
            or parsed.ip in {parsed.network.network_address, parsed.network.broadcast_address}):
        raise NetworkError("Choose a usable IPv4 host address and prefix /1 through /30")
    return {**values, "address": str(parsed)}


def run(arguments, *, timeout=8):
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NetworkError("Network service did not respond; previous settings are protected by rollback") from exc
    if result.returncode:
        raise NetworkError(result.stderr.strip()[:400] or "Network command failed")
    return result.stdout.strip()


class NetworkManager:
    def __init__(self, state=Path("/var/lib/spot-network/transaction.json"), runner=run):
        self.state, self.run = state, runner

    def nm(self, *args, timeout=8):
        return self.run(["nmcli", *args], timeout=timeout)

    def bus(self, method, signature="", *args):
        reply = self.run(["busctl", "--system", "--json=short", "call", NM, NM_PATH,
                          NM, method, signature, *map(str, args)])
        return json.loads(reply)["data"] if reply else []

    def checkpoints(self):
        reply = self.run(["busctl", "--system", "--json=short", "get-property", NM,
                          NM_PATH, NM, "Checkpoints"])
        return json.loads(reply)["data"]

    def rollback(self, checkpoint):
        self.bus("CheckpointRollback", "o", checkpoint)
        # NetworkManager 1.36 destroys a checkpoint as part of rollback.
        if checkpoint in self.checkpoints():
            self.bus("CheckpointDestroy", "o", checkpoint)

    def pending(self):
        if not self.state.exists():
            return None
        pending = json.loads(self.state.read_text())
        if pending["checkpoint"] not in self.checkpoints():
            if not pending.get("confirm_requested"):
                self.nm("connection", "delete", "uuid", pending["connection_uuid"])
            self.state.unlink(missing_ok=True)
            return None
        return pending

    def interfaces(self):
        active = {}
        for row in self.nm("-t", "-f", "UUID,DEVICE", "connection", "show", "--active").splitlines():
            identity, _, device = row.partition(":")
            active[device] = identity
        links = json.loads(self.run(["ip", "-json", "address", "show"]))
        result = []
        for link in links:
            name = link["ifname"]
            if not Path("/sys/class/net", name, "device").exists():
                continue
            if self.nm("-g", "GENERAL.TYPE", "device", "show", name) != "ethernet":
                continue
            identity = active.get(name)
            method = self.nm("-g", "ipv4.method", "connection", "show", "uuid", identity) if identity else ""
            result.append({"interface": name, "mac": link.get("address", ""),
                           "connected": "LOWER_UP" in link.get("flags", []),
                           "addresses": [f"{a['local']}/{a['prefixlen']}" for a in link.get("addr_info", []) if a['family'] == 'inet'],
                           "mode": "automatic" if method == "auto" else "static" if method == "manual" else "unconfigured",
                           "connection_uuid": identity})
        return result

    def status(self):
        pending = self.pending()
        hostname, discovery = "", "unavailable"
        try:
            reply = self.run(["busctl", "--system", "--json=short", "call", "org.freedesktop.Avahi",
                              "/", "org.freedesktop.Avahi.Server", "GetHostNameFqdn"])
            hostname = json.loads(reply)["data"][0]
            discovery = "active"
        except NetworkError:
            pass
        addresses = [a["local"] for link in json.loads(self.run(["ip", "-json", "address", "show"]))
                     for a in link.get("addr_info", []) if a["family"] == "inet"]
        return {"available": True, "interfaces": self.interfaces(), "hostname": hostname,
                "local_addresses": addresses,
                "discovery": discovery, "pending": ({"token": pending["token"],
                "interface": pending["interface"], "address": pending["address"],
                "remaining_s": max(0, round(pending["deadline"] - time.monotonic()))} if pending else None)}

    def apply(self, values):
        values = validate_change(values)
        if self.pending():
            raise NetworkError("Confirm or revert the pending network change first")
        interfaces = self.interfaces()
        selected = next((i for i in interfaces if i["interface"] == values["interface"]), None)
        if selected is None:
            raise NetworkError("Only a physical Ethernet port managed by NetworkManager can be changed")
        if values["mode"] == "static":
            network = ipaddress.IPv4Interface(values["address"]).network
            # Also include Wi-Fi, bridges and VPN addresses in the overlap check.
            for link in json.loads(self.run(["ip", "-json", "address", "show"])):
                if link["ifname"] == values["interface"]:
                    continue
                for a in link.get("addr_info", []):
                    if a["family"] == "inet" and network.overlaps(ipaddress.IPv4Network(f"{a['local']}/{a['prefixlen']}", strict=False)):
                        raise NetworkError("This subnet overlaps another Jetson port; choose separate subnets")
        device = self.nm("-g", "GENERAL.DBUS-PATH", "device", "show", values["interface"])
        checkpoint_at = time.monotonic()
        checkpoint = self.bus("CheckpointCreate", "aouu", 1, device, 90, 0)[0]
        identity, token = None, uuid.uuid4().hex
        try:
            name = "Spot-" + values["interface"] + "-" + token[:8]
            old = selected["connection_uuid"]
            priority = int(self.nm("-g", "connection.autoconnect-priority", "connection", "show", "uuid", old)) if old else 0
            if priority >= 999:
                raise NetworkError("Connection priority needs administrator review before another change")
            if old:
                self.nm("connection", "clone", "uuid", old, name)
            else:
                self.nm("connection", "add", "type", "ethernet", "ifname", values["interface"], "con-name", name)
            identity = self.nm("-g", "connection.uuid", "connection", "show", name)
            self.nm("connection", "modify", "uuid", identity, "connection.autoconnect", "no",
                    "connection.interface-name", values["interface"], "802-3-ethernet.mac-address", selected["mac"],
                    "ipv4.method", "auto" if values["mode"] == "automatic" else "manual",
                    "ipv4.addresses", values["address"], "ipv4.gateway", "", "ipv4.dns", "",
                    "ipv4.routes", "", "ipv4.never-default", "yes", "ipv4.ignore-auto-dns", "yes",
                    "ipv6.never-default", "yes", "ipv6.ignore-auto-dns", "yes", "ipv4.dad-timeout", "1500")
            pending = {**values, "token": token, "connection_uuid": identity,
                       "priority": priority + 1, "checkpoint": checkpoint,
                       "deadline": checkpoint_at + 90}
            self.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self.state.with_suffix(".next")
            temporary.write_text(json.dumps(pending));temporary.chmod(0o600)
            temporary.replace(self.state)
            self.nm("--wait", "45", "connection", "up", "uuid", identity, timeout=49)
        except Exception:
            self.rollback(checkpoint)
            if identity:
                self.nm("connection", "delete", "uuid", identity)
            self.state.unlink(missing_ok=True)
            raise
        return self.status()

    def finish(self, token, *, keep):
        pending = self.pending()
        if not pending or token != pending["token"]:
            raise NetworkError("This network change expired or was already reverted")
        if keep:
            current = next((i for i in self.interfaces() if i["interface"] == pending["interface"]), {})
            if current.get("connection_uuid") != pending["connection_uuid"] or not current.get("addresses"):
                raise NetworkError("The selected port has no active IPv4 connection; revert or wait for rollback")
            # Persist the user's confirmation before committing. If the helper
            # restarts after CheckpointDestroy, status must not delete a kept profile.
            pending["confirm_requested"] = True
            temporary = self.state.with_suffix(".next")
            temporary.write_text(json.dumps(pending));temporary.chmod(0o600)
            temporary.replace(self.state)
            self.nm("connection", "modify", "uuid", pending["connection_uuid"],
                    "connection.autoconnect-priority", str(pending["priority"]), "connection.autoconnect", "yes")
            self.bus("CheckpointDestroy", "o", pending["checkpoint"])
        else:
            self.rollback(pending["checkpoint"])
            self.nm("connection", "delete", "uuid", pending["connection_uuid"])
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
            connection.sendall((json.dumps({"operation": operation, "payload": payload}) + "\n").encode())
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
                self.snapshot = {"available": False, "error": "Network helper unavailable: " + str(exc)[:180]}
            self.stop.wait(3)

    def submit(self, operation, payload, guard=lambda: None):
        if not self.busy.acquire(blocking=False):
            future = Future();future.set_exception(NetworkError("Network change already in progress"));return future
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
    manager = NetworkManager()
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
