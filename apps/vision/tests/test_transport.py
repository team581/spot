from __future__ import annotations

import time

import numpy as np

from spot_vision.config import (
    CameraConfig,
    CameraSelector,
    DetectorConfig,
    NtConfig,
    ServiceConfig,
)
from spot_vision.headless_models import VisionFrame
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
from spot_vision.protocol import restore, snapshot
from spot_vision.transport import NtPublisher, make_vision_frame


def fixtures(tmp_path):
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
        3,
        DetectorConfig(),
    )
    config = ServiceConfig(
        1, None, 7, 0.1651, 32, NtConfig(enabled=False), (camera,), tmp_path / "config.json"
    )
    frame = FramePacket(
        "front", 4, 5, 123456, time.monotonic_ns(), np.zeros((8, 16, 2), dtype=np.uint8)
    )
    detection = Detection(2, np.array([[1, 2], [3, 4], [5, 6], [7, 8]], dtype=float), 0, 42)
    detected = DetectedFrame(frame, DetectionBatch((detection,), 2.5, 10), 3.0)
    candidate = PoseCandidate(
        PoseMethod.SINGLE_TAG_IPPE_SQUARE, np.array([1, 2, 3]), np.array([1, 0, 0, 0]), 0.2, (2,)
    )
    solution = PoseSolution((candidate,), frozenset({2}), {}, 0.5)
    return config, camera, detected, solution


def test_headless_frame_preserves_variable_results(tmp_path):
    config, camera, detected, solution = fixtures(tmp_path)
    message = make_vision_frame(config, camera, detected, solution, 4.0)
    decoded = restore(VisionFrame, snapshot(message))
    assert decoded.camera_id == "front"
    assert decoded.sequence == 4
    assert decoded.tags[0].corners_xy_px == [1, 2, 3, 4, 5, 6, 7, 8]
    assert decoded.tags[0].used_for_pose
    assert decoded.candidates[0].method == 2
    assert decoded.timing.total_ms == 4.0


def test_nt_publisher_keeps_duplicates_and_explicit_timestamp(tmp_path):
    import ntcore
    from wpimath.geometry import Pose3d

    config, camera, detected, solution = fixtures(tmp_path)
    publisher = NtPublisher(NtConfig(enabled=True, mode="server"), [camera.id])
    from spot_vision.structs import PoseEstimate

    subscriber = publisher.instance.getStructArrayTopic(
        "/Spot/front/output/observations", PoseEstimate
    ).subscribe(
        [],
        ntcore.PubSubOptions(keepDuplicates=True, pollStorage=16),
    )
    pose_subscriber = publisher.instance.getStructTopic(
        "/Spot/front/output/robot_pose", Pose3d
    ).subscribe(Pose3d(), ntcore.PubSubOptions(keepDuplicates=True, pollStorage=16))
    valid_subscriber = publisher.instance.getBooleanTopic(
        "/Spot/front/output/robot_pose_valid"
    ).subscribe(False, ntcore.PubSubOptions(keepDuplicates=True, pollStorage=16))
    from dataclasses import replace

    solution = replace(
        solution,
        candidates=(
            replace(solution.candidates[0], average_tag_distance_m=3.25, distortion_factor_px=12.5),
        ),
    )
    distance_subscriber = publisher.instance.getDoubleTopic(
        "/Spot/front/output/robot_pose_average_tag_distance_m"
    ).subscribe(-1, ntcore.PubSubOptions(keepDuplicates=True, pollStorage=16))
    distortion_subscriber = publisher.instance.getDoubleTopic(
        "/Spot/front/output/robot_pose_distortion_factor_px"
    ).subscribe(-1, ntcore.PubSubOptions(keepDuplicates=True, pollStorage=16))
    message = make_vision_frame(config, camera, detected, solution, 4.0)
    timestamp = detected.frame.capture_timestamp_us
    counters = CameraCounters()
    robot_pose = solution.candidates[0]
    publisher.publish_frame(camera, 7, message, timestamp, counters, 40.0, robot_pose)
    publisher.publish_frame(camera, 7, message, timestamp + 1, counters, 40.0, robot_pose)
    publisher.publish_frame(camera, 7, message, timestamp + 2, counters, 40.0, None)
    publisher.instance.flush()
    deadline = time.monotonic() + 1
    updates = []
    while len(updates) < 2 and time.monotonic() < deadline:
        updates.extend(subscriber.readQueue())
        time.sleep(0.005)
    pose_updates = pose_subscriber.readQueue()
    valid_updates = valid_subscriber.readQueue()
    distance_updates = distance_subscriber.readQueue()
    distortion_updates = distortion_subscriber.readQueue()
    publisher.close()
    assert [update.value for update in distance_updates[-3:]] == [3.25, 3.25, 0.0]
    assert [update.value for update in distortion_updates[-3:]] == [12.5, 12.5, 0.0]
    assert [update.time for update in distance_updates[-3:]] == [
        timestamp,
        timestamp + 1,
        timestamp + 2,
    ]
    assert [update.time for update in updates[-3:]] == [timestamp, timestamp + 1, timestamp + 2]
    assert all(len(update.value) == 1 and update.value[0].method == 2 for update in updates[-3:])
    assert [update.time for update in pose_updates[-2:]] == [timestamp, timestamp + 1]
    assert all(np.isclose(update.value.X(), 1.0) for update in pose_updates[-2:])
    assert [update.value for update in valid_updates[-3:]] == [True, True, False]
    assert [update.time for update in valid_updates[-3:]] == [
        timestamp,
        timestamp + 1,
        timestamp + 2,
    ]


def test_distortion_transport_distinguishes_missing_calibration_and_preserves_metrics(tmp_path):
    from dataclasses import replace

    config, camera, detected, solution = fixtures(tmp_path)
    message = make_vision_frame(config, camera, detected, solution, 4.0)
    assert message.tags[0].distortion_factor_px is None
    observed = replace(detected.batch.detections[0], distortion_factor_px=12.5)
    detected = replace(detected, batch=replace(detected.batch, detections=(observed,)))
    candidate = replace(
        solution.candidates[0], average_tag_distance_m=3.25, distortion_factor_px=12.5
    )
    solution = replace(solution, candidates=(candidate,))
    message = restore(
        VisionFrame, snapshot(make_vision_frame(config, camera, detected, solution, 4.0))
    )
    assert message.tags[0].distortion_factor_px is not None
    assert message.tags[0].distortion_factor_px == 12.5
    assert message.candidates[0].distortion_factor_px == 12.5
    assert message.candidates[0].average_tag_distance_m == 3.25
    from spot_vision.pose import robot_from_camera_transform, select_robot_pose

    robot = select_robot_pose(solution, robot_from_camera_transform((0.5, 0.1, 0)))
    assert robot.average_tag_distance_m == 3.25
    assert robot.distortion_factor_px == 12.5
