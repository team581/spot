from spot_vision.devices import (
    DeviceManager,
    DeviceNode,
    DeviceRegistry,
    parse_capability_controls,
    parse_modes,
)


def node(path="/dev/video0", port="usb-1", serial="unique", capture=True):
    return DeviceNode(path, port, "1234", "5678", serial, "Generic USB Camera", capture)


def test_camera_slot_survives_restart_and_stays_with_physical_port(tmp_path):
    registry = DeviceRegistry(tmp_path)
    first = registry.identify([node()])[0]
    rebooted = DeviceRegistry(tmp_path).identify([node(path="/dev/video6")])[0]
    assert rebooted.identity == first.identity and rebooted.display_id == first.display_id
    moved = DeviceRegistry(tmp_path).identify([node(path="/dev/video8", port="usb-8")])[0]
    assert first.identity != moved.identity and first.display_id != moved.display_id
    assert moved.capture_node == "/dev/video8" and moved.unique_serial
    returned = DeviceRegistry(tmp_path).identify([node(path="/dev/video10")])[0]
    assert returned.identity == first.identity and returned.display_id == first.display_id


def test_duplicate_or_missing_serial_uses_port_not_enumeration_and_remembers_duplicates(tmp_path):
    registry = DeviceRegistry(tmp_path)
    a, b = registry.identify([node(port="a"), node(path="/dev/video3", port="b")])
    assert a.identity != b.identity and not a.unique_serial and not b.unique_serial
    restarted = DeviceRegistry(tmp_path)
    only_a = restarted.identify([node(path="/dev/video5", port="a")])[0]
    assert only_a.identity == a.identity and not only_a.unique_serial
    moved = restarted.identify([node(port="c")])[0]
    assert moved.identity != a.identity
    missing = registry.identify([node(serial="", port="missing")])[0]
    assert not missing.unique_serial


def test_metadata_nodes_group_with_physical_device_and_replacement_identity_changes(tmp_path):
    registry = DeviceRegistry(tmp_path)
    first = registry.identify([node(), node(path="/dev/video1", capture=False)])[0]
    assert first.nodes == ("/dev/video0", "/dev/video1") and first.capture_node == "/dev/video0"
    replacement = registry.identify([node(serial="new")])[0]
    assert replacement.identity != first.identity
    assert replacement.display_id == first.display_id


def test_ports_do_not_swap_labels_or_device_identity_when_cameras_are_swapped(tmp_path):
    registry = DeviceRegistry(tmp_path)
    a, b = registry.identify([node(port="a", serial="first"),
                              node(port="b", serial="second", path="/dev/video2")])
    swapped = DeviceRegistry(tmp_path).identify([
        node(port="b", serial="first"), node(port="a", serial="second", path="/dev/video2"),
    ])
    by_port = {device.topology: device for device in swapped}
    assert by_port["a"].display_id == a.display_id and by_port["b"].display_id == b.display_id
    assert by_port["a"].identity not in {a.identity, b.identity}
    assert by_port["b"].identity not in {a.identity, b.identity}
    restored = DeviceRegistry(tmp_path).identify([
        node(port="b", serial="second"), node(port="a", serial="first", path="/dev/video4"),
    ])
    assert {d.identity for d in restored} == {a.identity, b.identity}


def test_legacy_registry_adopts_current_port_without_losing_saved_identity(tmp_path):
    import hashlib
    import json

    identity = hashlib.sha256(b"serial:1234:5678:unique").hexdigest()
    (tmp_path / "devices.json").write_text(json.dumps({
        "schema_version": 1, "display_ids": {identity: "USB-03"},
        "duplicate_serials": [], "next_id": 4,
    }))
    current = DeviceRegistry(tmp_path).identify([node()])[0]
    assert current.identity == identity and current.display_id == "USB-03"
    persisted = json.loads((tmp_path / "devices.json").read_text())
    assert persisted["port_slots"]["usb-1"]["display_id"] == "USB-03"


def test_capabilities_use_advertised_units_menus_flags_and_modes():
    output = """[0]: 'MJPG' (Motion-JPEG)
        Size: Discrete 640x480
        Interval: Discrete 0.033s (30.000 fps)
        Size: Discrete 1920x1080
        Interval: Discrete 0.008s (120.000 fps)
     exposure_time_absolute 0x009a0902 (int) : min=50 max=10000 step=1 default=100 value=50
     special_vendor_control 0x009a0903 (menu) : min=0 max=2 default=0 value=0 flags=read-only
        0: Off
        2: High
    """
    modes = parse_modes(output)
    assert modes[0]["width"] == 640 and modes[1]["fps"] == 120
    assert all(not mode["verified"] for mode in modes)
    exposure, vendor = parse_capability_controls(output)
    assert exposure["min"] == 50 and exposure["factor"] == 100
    assert not vendor["writable"] and vendor["options"][1]["value"] == 2


def test_discovery_capability_failure_is_per_camera_and_disconnect_does_not_retain_stale(tmp_path):
    nodes = [node(port="a"), node(path="/dev/video2", port="b", serial="other")]
    from spot_vision.config import ConfigError

    def capabilities(path):
        if path == "/dev/video2":
            raise ConfigError("read timed out")
        return "[0]: 'YUYV' (YUYV)\nSize: Discrete 640x480\nInterval: Discrete 0.033s (30.000 fps)"

    manager = DeviceManager(
        DeviceRegistry(tmp_path), enumerate_fn=lambda: nodes, capability_fn=capabilities
    )
    manager.refresh()
    assert len(manager.snapshot()) == 2
    assert sum(bool(device["fault"]) for device in manager.snapshot()) == 1
    nodes.clear()
    manager.refresh()
    assert not manager.snapshot()
