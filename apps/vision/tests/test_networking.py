import json

import pytest

from spot_vision.networking import NetworkError, NetworkManager, validate_change


def change(**values):
    return {"interface": "eth0", "mode": "static", "address": "10.5.81.11/24", **values}


@pytest.mark.parametrize(
    "values",
    [
        change(interface="eth0;reboot"),
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


def test_static_and_automatic_are_distinct():
    assert validate_change(change())["address"] == "10.5.81.11/24"
    assert validate_change(change(mode="automatic", address=""))["address"] == ""


class FakeManager(NetworkManager):
    def __init__(self, tmp_path):
        super().__init__(tmp_path / "pending.json", self.command)
        self.calls, self.live_checkpoints = [], []
        self.fail_activation = False
        self.ports = [
            {
                "interface": "eth0",
                "mac": "aa:bb:cc:dd:ee:ff",
                "addresses": ["10.5.81.10/24"],
                "connection_uuid": "old",
                "mode": "static",
            }
        ]

    def command(self, args, **kwargs):
        self.calls.append(args)
        return json.dumps(
            [
                {
                    "ifname": "management",
                    "addr_info": [{"family": "inet", "local": "192.168.69.170", "prefixlen": 24}],
                }
            ]
        )

    def nm(self, *args, **kwargs):
        self.calls.append(args)
        if args[:3] == ("-g", "GENERAL.DBUS-PATH", "device"):
            return "/devices/1"
        if args[:2] == ("-g", "connection.autoconnect-priority"):
            return "10"
        if args[:2] == ("-g", "connection.uuid"):
            return "new"
        if args[:3] == ("--wait", "45", "connection"):
            if self.fail_activation:
                raise NetworkError("DHCP timed out")
            self.ports[0].update(connection_uuid="new", addresses=["10.5.81.11/24"])
        return ""

    def bus(self, method, *args):
        self.calls.append((method, *args))
        if method == "CheckpointCreate":
            self.live_checkpoints = ["/checkpoint/1"]
            return ["/checkpoint/1"]
        if method == "CheckpointRollback":
            self.live_checkpoints = []
        if method == "CheckpointDestroy":
            if not self.live_checkpoints:
                raise NetworkError("checkpoint does not exist")
            self.live_checkpoints = []
        return []

    def interfaces(self):
        return self.ports

    def checkpoints(self):
        return self.live_checkpoints

    def status(self):
        return {"pending": self.pending(), "interfaces": self.ports}


def test_apply_clones_profile_and_does_not_make_unconfirmed_settings_boot_defaults(tmp_path):
    manager = FakeManager(tmp_path)
    pending = manager.apply(change())["pending"]
    assert pending["connection_uuid"] == "new"
    assert ("CheckpointCreate", "aouu", 1, "/devices/1", 90, 0) in manager.calls
    modifications = [c for c in manager.calls if c[:2] == ("connection", "modify")]
    assert len(modifications) == 1
    assert modifications[0][3] == "new"  # Original connection is never edited.
    assert ("connection.autoconnect", "no") == modifications[0][4:6]
    manager.finish(pending["token"], keep=True)
    assert not manager.state.exists()
    assert (
        "connection",
        "modify",
        "uuid",
        "new",
        "connection.autoconnect-priority",
        "11",
        "connection.autoconnect",
        "yes",
    ) in manager.calls
    assert ("CheckpointDestroy", "o", "/checkpoint/1") in manager.calls


def test_activation_failure_rolls_back_and_removes_new_profile_checkpoint(tmp_path):
    manager = FakeManager(tmp_path)
    manager.fail_activation = True
    with pytest.raises(NetworkError, match="DHCP"):
        manager.apply(change(mode="automatic", address=""))
    assert ("CheckpointRollback", "o", "/checkpoint/1") in manager.calls
    assert ("CheckpointDestroy", "o", "/checkpoint/1") not in manager.calls
    assert ("connection", "delete", "uuid", "new") in manager.calls
    assert not manager.state.exists()


def test_overlapping_subnet_and_non_ethernet_rejected_before_changes(tmp_path):
    manager = FakeManager(tmp_path)
    for values in [change(address="192.168.69.11/24"), change(interface="wlan0")]:
        with pytest.raises(NetworkError):
            manager.apply(values)
    assert not any(c[0] == "CheckpointCreate" for c in manager.calls)


def test_expired_checkpoint_cannot_be_confirmed_and_clears_stale_state(tmp_path):
    manager = FakeManager(tmp_path)
    pending = manager.apply(change())["pending"]
    manager.live_checkpoints = []  # NetworkManager already timed out and reverted it.
    with pytest.raises(NetworkError, match="expired"):
        manager.finish(pending["token"], keep=True)
    assert not manager.state.exists()


def test_confirm_rejects_missing_ipv4_and_revert_still_works(tmp_path):
    manager = FakeManager(tmp_path)
    pending = manager.apply(change())["pending"]
    manager.ports[0]["addresses"] = []
    with pytest.raises(NetworkError, match="no active IPv4"):
        manager.finish(pending["token"], keep=True)
    manager.finish(pending["token"], keep=False)
    assert ("CheckpointRollback", "o", "/checkpoint/1") in manager.calls


def test_checkpoint_property_accepts_empty_actual_busctl_array(tmp_path):
    manager = NetworkManager(tmp_path / "pending", lambda *a, **_kw: '{"type":"ao","data":[]}')
    assert manager.checkpoints() == []


def test_restart_after_confirm_does_not_delete_the_kept_connection(tmp_path):
    manager = FakeManager(tmp_path)
    pending = manager.apply(change())["pending"]
    pending["confirm_requested"] = True
    manager.state.write_text(json.dumps(pending))
    manager.live_checkpoints = []  # CheckpointDestroy completed before helper restart.
    manager.calls.clear()
    assert manager.pending() is None
    assert not any(c[:2] == ("connection", "delete") for c in manager.calls)
