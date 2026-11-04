import copy
import json

import pytest

from spot_vision.networking import (
    SAVED_CONNECTION,
    NetworkError,
    NetworkManager,
    validate_change,
)

MAINTENANCE = "192.168.69.170/24"
DEFAULT = "nix-default"


def change(**values):
    return {"mode": "static", "address": "10.5.81.11/24", **values}


@pytest.mark.parametrize(
    "values",
    [
        change(interface="spot0"),
        change(address="10.5.81.11"),
        change(address="10.5.81.0/24"),
        change(address="10.5.81.255/24"),
        change(address="127.0.0.1/24"),
        change(address="224.0.0.1/24"),
        change(address="0.0.0.0/24"),
        change(address="10.5.81.11/31"),
        change(mode="automatic"),
        change(mode="shell"),
        {**change(), "command": "anything"},
    ],
)
def test_address_validation_rejects_unsafe_or_ambiguous_input(values):
    with pytest.raises(NetworkError):
        validate_change(values)


class FakeManager(NetworkManager):
    """Stateful NM peer: temporary profiles, persistent profiles and checkpoints."""

    def __init__(self, tmp_path):
        super().__init__("br0", MAINTENANCE, DEFAULT, tmp_path / "pending.json", self.command)
        self.calls, self.live_checkpoints = [], {}
        self.fail_activation = self.fail_commit = False
        self.dhcp_address = "10.5.81.77/24"
        self.carrier = True
        self.actual_addresses = None
        self.other_links = []
        self.device_type = "bridge"
        self.active, self.counter = DEFAULT, 0
        self.profiles = {
            DEFAULT: {
                "connection.id": "Spot maintenance",
                "connection.autoconnect": "yes",
                "connection.autoconnect-priority": "0",
                "ipv4.method": "manual",
                "ipv4.addresses": MAINTENANCE,
                "bridge.stp": "yes",
                "persisted": True,
            },
        }

    def command(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "ip":
            profile = self.profiles[self.active]
            addresses = profile["ipv4.addresses"].split(",")
            if profile["ipv4.method"] == "auto" and self.dhcp_address:
                addresses.append(self.dhcp_address)
            if self.actual_addresses is not None:
                addresses = self.actual_addresses
            return json.dumps(
                [
                    {
                        "ifname": "br0",
                        "flags": ["LOWER_UP"] if self.carrier else [],
                        "addr_info": [
                            {
                                "family": "inet",
                                "local": a.split("/")[0],
                                "prefixlen": int(a.split("/")[1]),
                            }
                            for a in addresses
                        ],
                    },
                    *self.other_links,
                ]
            )
        if args[-1] == "Checkpoints":
            return json.dumps({"data": list(self.live_checkpoints)})
        if args[-1] == "GetHostNameFqdn":
            return json.dumps({"data": ["spot.local"]})
        raise AssertionError(args)

    def nm(self, *args, **kwargs):
        self.calls.append(args)
        if args[:3] == ("-t", "-f", "UUID,NAME"):
            return "\n".join(f"{key}:{p['connection.id']}" for key, p in self.profiles.items())
        if args[0] == "-g":
            field = args[1]
            if field == "GENERAL.TYPE":
                assert args[-1] == "br0"
                return self.device_type
            if field == "GENERAL.CON-UUID":
                return self.active
            if field == "GENERAL.DBUS-PATH":
                return "/devices/br0"
            if field == "connection.uuid":
                return next(
                    key for key, p in self.profiles.items() if p["connection.id"] == args[-1]
                )
            return self.profiles[args[-1]][field]
        if args[:2] == ("connection", "clone"):
            assert args[2:5] == ("--temporary", "uuid", DEFAULT)
            self.counter += 1
            self.profiles[f"trial-{self.counter}"] = {
                **copy.deepcopy(self.profiles[DEFAULT]),
                "connection.id": args[-1],
                "persisted": False,
            }
        elif args[:2] == ("connection", "modify"):
            temporary = args[2] == "--temporary"
            offset = 3 if temporary else 2
            assert args[offset] == "uuid"
            profile = self.profiles[args[offset + 1]]
            if self.fail_commit and not temporary:
                raise NetworkError("Profile save interrupted")
            profile.update(dict(zip(args[offset + 2 :: 2], args[offset + 3 :: 2])))
            if not temporary:
                profile["persisted"] = True
        elif args[:2] == ("connection", "delete"):
            del self.profiles[args[-1]]
        elif args[:3] == ("--wait", "45", "connection"):
            if self.fail_activation:
                raise NetworkError("Activation timed out")
            self.active = args[-1]
        else:
            raise AssertionError(args)
        return ""

    def bus(self, method, *args):
        self.calls.append((method, *args))
        if method == "CheckpointCreate":
            self.live_checkpoints["/checkpoint/1"] = self.active
            return ["/checkpoint/1"]
        if method == "CheckpointRollback":
            self.active = self.live_checkpoints.pop(args[-1])
        elif method == "CheckpointDestroy":
            del self.live_checkpoints[args[-1]]
        elif method == "CheckpointAdjustRollbackTimeout":
            assert args[-2] in self.live_checkpoints
        else:
            raise AssertionError(method)
        return []

    def expire(self):
        self.active = self.live_checkpoints.pop("/checkpoint/1")


@pytest.mark.parametrize("mode", ["static", "automatic"])
def test_trial_preserves_maintenance_and_is_not_a_boot_default(tmp_path, mode):
    manager = FakeManager(tmp_path)
    original = copy.deepcopy(manager.profiles[DEFAULT])
    result = manager.apply(
        change(mode=mode, address="" if mode == "automatic" else "10.5.81.11/24")
    )
    trial = manager.profiles[manager.active]
    assert result["maintenance_address"] == MAINTENANCE
    assert MAINTENANCE in result["addresses"]
    assert ("10.5.81.77/24" if mode == "automatic" else "10.5.81.11/24") in result["addresses"]
    assert trial["connection.autoconnect"] == "no" and not trial["persisted"]
    assert trial["bridge.stp"] == "yes"
    assert manager.profiles[DEFAULT] == original
    assert "interfaces" not in result and "interface" not in result["pending"]
    manager.finish(result["pending"]["token"], keep=True)
    assert trial["persisted"] and trial["connection.autoconnect"] == "yes"
    assert trial["connection.id"] == SAVED_CONNECTION
    assert trial["connection.autoconnect-priority"] == "100"
    assert manager.profiles[DEFAULT] == original
    assert not manager.state.exists()


def test_repeated_edits_replace_previous_override_without_profile_or_priority_growth(tmp_path):
    manager = FakeManager(tmp_path)
    for value in range(11, 21):
        result = manager.apply(change(address=f"10.5.81.{value}/24"))
        assert len(manager.profiles) <= 3  # Nix default, saved override, trial.
        manager.finish(result["pending"]["token"], keep=True)
        assert len(manager.profiles) == 2
        assert manager.profiles[manager.active]["connection.autoconnect-priority"] == "100"


def test_activation_failure_restores_previous_connection(tmp_path):
    manager = FakeManager(tmp_path)
    manager.fail_activation = True
    with pytest.raises(NetworkError, match="timed out"):
        manager.apply(change())
    assert manager.active == DEFAULT and list(manager.profiles) == [DEFAULT]
    assert not manager.state.exists() and not manager.live_checkpoints


def test_timeout_discards_trial_and_cannot_be_confirmed(tmp_path):
    manager = FakeManager(tmp_path)
    token = manager.apply(change())["pending"]["token"]
    manager.expire()
    with pytest.raises(NetworkError, match="expired"):
        manager.finish(token, keep=True)
    assert list(manager.profiles) == [DEFAULT] and not manager.state.exists()


@pytest.mark.parametrize("addresses", [[MAINTENANCE], ["10.5.81.11/24"]])
def test_confirm_requires_both_maintenance_and_robot_addresses(tmp_path, addresses):
    manager = FakeManager(tmp_path)
    token = manager.apply(change())["pending"]["token"]
    manager.actual_addresses = addresses
    with pytest.raises(NetworkError, match="both"):
        manager.finish(token, keep=True)
    manager.actual_addresses = None
    manager.finish(token, keep=False)
    assert manager.active == DEFAULT and list(manager.profiles) == [DEFAULT]


def test_trial_waits_for_carrier_before_confirmation(tmp_path):
    manager = FakeManager(tmp_path)
    manager.carrier = False
    token = manager.apply(change())["pending"]["token"]
    with pytest.raises(NetworkError, match="both"):
        manager.finish(token, keep=True)
    assert not manager.profiles[manager.active]["persisted"]
    manager.carrier = True
    manager.finish(token, keep=True)
    assert manager.profiles[manager.active]["persisted"]


def test_dhcp_without_a_robot_address_cannot_be_confirmed_and_times_out(tmp_path):
    manager = FakeManager(tmp_path)
    manager.dhcp_address = ""
    token = manager.apply(change(mode="automatic", address=""))["pending"]["token"]
    with pytest.raises(NetworkError, match="both"):
        manager.finish(token, keep=True)
    manager.expire()
    assert manager.pending() is None
    assert manager.active == DEFAULT and list(manager.profiles) == [DEFAULT]


def test_maintenance_address_and_other_networks_are_protected(tmp_path):
    manager = FakeManager(tmp_path)
    manager.other_links = [
        {
            "ifname": "wlan0",
            "addr_info": [{"family": "inet", "local": "10.5.81.50", "prefixlen": 24}],
        }
    ]
    with pytest.raises(NetworkError, match="overlaps"):
        manager.apply(change())
    with pytest.raises(NetworkError, match="fixed by NixOS"):
        manager.apply(change(address=MAINTENANCE))
    assert not manager.live_checkpoints and list(manager.profiles) == [DEFAULT]


def test_unmanaged_connection_cannot_be_changed_or_deleted(tmp_path):
    manager = FakeManager(tmp_path)
    manager.profiles["foreign"] = {**manager.profiles[DEFAULT], "connection.id": "Administrator"}
    manager.active = "foreign"
    with pytest.raises(NetworkError, match="not managed"):
        manager.apply(change())
    manager.delete_owned("foreign")
    manager.delete_owned(DEFAULT)
    assert set(manager.profiles) == {DEFAULT, "foreign"}


def test_wrong_device_type_is_rejected(tmp_path):
    manager = FakeManager(tmp_path)
    manager.device_type = "ethernet"
    with pytest.raises(NetworkError, match="bridge"):
        manager.apply(change())
    assert list(manager.profiles) == [DEFAULT]


def test_failed_confirmation_followed_by_timeout_never_saves_trial(tmp_path):
    manager = FakeManager(tmp_path)
    token = manager.apply(change())["pending"]["token"]
    manager.fail_commit = True
    with pytest.raises(NetworkError, match="interrupted"):
        manager.finish(token, keep=True)
    manager.expire()
    assert manager.pending() is None
    assert list(manager.profiles) == [DEFAULT]


def test_restart_during_confirmation_finishes_old_override_cleanup(tmp_path, monkeypatch):
    manager = FakeManager(tmp_path)
    first = manager.apply(change())
    manager.finish(first["pending"]["token"], keep=True)
    previous = manager.active
    second = manager.apply(change(address="10.5.81.12/24"))
    delete_owned = manager.delete_owned

    def interrupted(identity):
        if identity == previous:
            raise NetworkError("Helper stopped after confirmation")
        delete_owned(identity)

    monkeypatch.setattr(manager, "delete_owned", interrupted)
    with pytest.raises(NetworkError, match="stopped"):
        manager.finish(second["pending"]["token"], keep=True)
    assert manager.state.exists() and not manager.live_checkpoints
    monkeypatch.setattr(manager, "delete_owned", delete_owned)
    assert manager.pending() is None
    assert set(manager.profiles) == {DEFAULT, manager.active}
    assert manager.profiles[manager.active]["persisted"]


def test_nm_restart_loses_temporary_trial_and_retains_saved_connection(tmp_path):
    manager = FakeManager(tmp_path)
    manager.apply(change())
    manager.profiles = {key: p for key, p in manager.profiles.items() if p["persisted"]}
    manager.active = DEFAULT
    manager.live_checkpoints.clear()
    assert manager.pending() is None
    assert list(manager.profiles) == [DEFAULT]


def test_status_distinguishes_configured_robot_address_from_maintenance(tmp_path):
    manager = FakeManager(tmp_path)
    assert manager.status()["address"] == ""
    result = manager.apply(change())
    assert result["address"] == "10.5.81.11/24"
    assert result["local_addresses"] == ["192.168.69.170", "10.5.81.11"]
