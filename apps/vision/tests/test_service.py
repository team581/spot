from __future__ import annotations

import logging
import threading
import time

import numpy as np

from spot_vision.config import (
    CameraConfig,
    CameraSelector,
    DetectorConfig,
    NtConfig,
    ServiceConfig,
)
from spot_vision.models import (
    CameraCounters,
    DetectedFrame,
    Detection,
    DetectionBatch,
    FramePacket,
    PoseCandidate,
    PoseMethod,
    PoseSolution,
)
from spot_vision.queues import BoundedDropOldestQueue
from spot_vision.service import OutputWorker
from spot_vision.transport import MemoryPublisher


class Solver:
    def solve(self, _detections):
        return PoseSolution()


class AmbiguousSolver:
    def solve(self, _detections):
        worse = PoseCandidate(
            PoseMethod.SINGLE_TAG_IPPE_SQUARE,
            np.array([9.0, 9.0, 9.0]),
            np.array([1.0, 0.0, 0.0, 0.0]),
            0.4,
            (8,),
        )
        better = PoseCandidate(
            PoseMethod.SINGLE_TAG_IPPE_SQUARE,
            np.array([1.0, 2.0, 3.0]),
            np.array([1.0, 0.0, 0.0, 0.0]),
            0.1,
            (8,),
        )
        return PoseSolution((worse, better), frozenset({8}))


def test_output_worker_publishes_tag_frame(tmp_path, caplog):
    camera = CameraConfig(
        "front",
        True,
        CameraSelector(device="/dev/null"),
        "YUY2",
        16,
        8,
        60,
        None,
        None,
        False,
        None,
        0,
        1,
        DetectorConfig(),
    )
    config = ServiceConfig(
        1, None, 0, 0.1651, 2, NtConfig(enabled=False), (camera,), tmp_path / "spot.json"
    )
    packet = FramePacket(
        "front", 4, 4, 123, time.monotonic_ns(), np.zeros((8, 16, 2), dtype=np.uint8)
    )
    detection = Detection(8, np.zeros((4, 2)), 0, 100)
    detected = DetectedFrame(packet, DetectionBatch((detection,), 6.0), 7.0)
    queue = BoundedDropOldestQueue(2)
    queue.put(detected)
    publisher = MemoryPublisher()
    stop = threading.Event()

    worker = OutputWorker(
        config,
        {"front": camera},
        {"front": CameraCounters()},
        {"front": Solver()},
        queue,
        publisher,
        stop,
        0,
    )
    caplog.set_level(logging.DEBUG)
    worker.start()
    deadline = time.monotonic() + 1
    while not publisher.frames and time.monotonic() < deadline:
        time.sleep(0.005)
    stop.set()
    queue.close()
    worker.join(1)

    assert len(publisher.frames) == 1
    from spot_vision.proto import VisionFrame

    message = VisionFrame.FromString(publisher.frames[0][1])
    assert message.camera_id == "front"
    assert message.tags[0].id == 8


def test_output_worker_emits_one_selected_robot_pose_for_ambiguous_frame(tmp_path):
    camera = CameraConfig(
        "left",
        True,
        CameraSelector(device="/dev/null"),
        "YUY2",
        16,
        8,
        60,
        None,
        None,
        False,
        None,
        0,
        1,
        DetectorConfig(),
    )
    config = ServiceConfig(
        1, None, 0, 0.1651, 2, NtConfig(enabled=False), (camera,), tmp_path / "spot.json"
    )
    packet = FramePacket(
        "left", 4, 4, 123, time.monotonic_ns(), np.zeros((8, 16, 2), dtype=np.uint8)
    )
    detected = DetectedFrame(packet, DetectionBatch((Detection(8, np.zeros((4, 2))),), 6.0), 7.0)
    queue = BoundedDropOldestQueue(2)
    queue.put(detected)
    publisher = MemoryPublisher()
    stop = threading.Event()
    worker = OutputWorker(
        config,
        {"left": camera},
        {"left": CameraCounters()},
        {"left": AmbiguousSolver()},
        queue,
        publisher,
        stop,
        0,
    )
    worker.start()
    deadline = time.monotonic() + 1
    while not publisher.robot_poses and time.monotonic() < deadline:
        time.sleep(0.005)
    stop.set()
    queue.close()
    worker.join(1)

    assert len(publisher.robot_poses) == 1
    camera_id, pose, timestamp = publisher.robot_poses[0]
    assert camera_id == "left" and timestamp == 123 and pose is not None
    assert pose.reprojection_error_px == 0.1
    assert np.array_equal(pose.translation, [1.0, 2.0, 3.0])
