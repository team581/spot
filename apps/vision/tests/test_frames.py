from __future__ import annotations

import time

import numpy as np
import pytest

from spot_vision.frames import FrameHub
from spot_vision.models import DetectedFrame, Detection, DetectionBatch, FramePacket, PoseSolution


def test_preview_uses_one_coherent_processed_frame_and_bounds_clients():
    hub = FrameHub(max_clients=1)
    packet = FramePacket(
        "one", 1, 1, time.monotonic_ns(), np.zeros((8, 8, 2), np.uint8), "epoch", "generation"
    )
    detection = Detection(1, np.array([[1, 1], [5, 1], [5, 5], [1, 5]], float), 0, 100)
    detected = DetectedFrame(packet, DetectionBatch((detection,), 1), 1)
    hub.capture(packet)
    hub.result(
        detected,
        PoseSolution(
            used_tag_ids=frozenset([1]), tag_diagnostics={1: {"distance_m": 2.0, "error_px": 0.2}}
        ),
    )
    hub.preview("one", "browser1")
    hub.start()
    try:
        deadline = time.monotonic() + 2
        result = {}
        while not result.get("image") and time.monotonic() < deadline:
            time.sleep(0.01)
            result = hub.preview("one", "browser1")
        assert (
            result["processed"] and result["sequence"] == 1 and result["capture_epoch"] == "epoch"
        )
        assert result["tags"][0]["error_px"] == 0.2 and result["tags"][0]["distance_m"] == 2
        with pytest.raises(ValueError, match="limit"):
            hub.preview("one", "browser2")
    finally:
        hub.close()


def test_disconnected_bound_image_retains_age_but_unbound_snapshots_are_pruned():
    hub = FrameHub()
    packet = FramePacket(
        "bound", 1, 1, time.monotonic_ns() - 1_000_000_000, np.zeros((8, 8, 2), np.uint8)
    )
    hub.capture(packet)
    hub.capture(FramePacket("extra", 1, 1, 1, packet.image))
    hub.encoded = {
        "bound": {
            "image": "last",
            "tags": [{"id": 1}],
            "captured_monotonic_ns": packet.captured_monotonic_ns,
        },
        "extra": {"image": "unused"},
    }
    hub.retain({"bound"})
    assert set(hub.latest) == set(hub.encoded) == {"bound"}
    result = hub.preview("bound", "browser")
    assert (
        result["image"] == "last"
        and result["stale"]
        and result["age_s"] >= 1
        and result["tags"] == []
    )
