from spot_vision.devices import (
    DeviceManager,
    DeviceNode,
    DeviceRegistry,
    parse_capability_controls,
    parse_modes,
)


def node(path="/dev/video0", port="usb-1", serial="unique", capture=True):
    return DeviceNode(path, port, "1234", "5678", serial, "Generic USB Camera", capture)


def test_unique_serial_follows_port_and_display_id_survives_restart(tmp_path):
    registry = DeviceRegistry(tmp_path)
    first = registry.identify([node()])[0]
    moved = DeviceRegistry(tmp_path).identify([node(path="/dev/video8", port="usb-8")])[0]
    assert first.identity == moved.identity and first.display_id == moved.display_id
    assert moved.capture_node == "/dev/video8" and moved.unique_serial


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
