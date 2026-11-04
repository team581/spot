from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import CameraConfig, NtConfig, ServiceConfig
from .models import CameraCounters, DetectedFrame, PoseCandidate, PoseSolution
from .proto import vision_pb2

LOGGER = logging.getLogger(__name__)
_POSE_METHOD_NAMES = {
    0: "METHOD_UNKNOWN",
    1: "MULTI_TAG_SQPNP",
    2: "SINGLE_TAG_IPPE_SQUARE",
}


def make_vision_frame(
    config: ServiceConfig,
    camera: CameraConfig,
    detected: DetectedFrame,
    solution: PoseSolution,
    total_ms: float,
) -> vision_pb2.VisionFrame:
    message = vision_pb2.VisionFrame(
        schema_version=config.schema_version,
        camera_id=camera.id,
        sequence=detected.frame.sequence,
        camera_frame_sequence=detected.frame.camera_frame_sequence,
        config_revision=camera.config_revision,
        field_revision=config.field_revision,
    )
    for candidate in solution.candidates:
        pose = message.candidates.add()
        pose.method = int(candidate.method)
        pose.x_m, pose.y_m, pose.z_m = (float(value) for value in candidate.translation)
        pose.qw, pose.qx, pose.qy, pose.qz = (float(value) for value in candidate.quaternion_wxyz)
        pose.reprojection_error_px = candidate.reprojection_error_px
        pose.tag_ids.extend(candidate.tag_ids)
        pose.average_tag_distance_m = candidate.average_tag_distance_m
        pose.distortion_factor_px = candidate.distortion_factor_px
    for detection in detected.batch.detections:
        observation = message.tags.add()
        observation.id = detection.id
        observation.corners_xy_px.extend(float(value) for value in detection.corners.reshape(-1))
        observation.hamming = detection.hamming
        observation.decision_margin = detection.decision_margin
        if detection.distortion_factor_px is not None:
            observation.distortion_factor_px = detection.distortion_factor_px
        observation.used_for_pose = detection.id in solution.used_tag_ids
        observation.rejection_reason = solution.rejection_reasons.get(detection.id, "")
    message.timing.capture_to_detect_ms = detected.capture_to_detect_ms
    message.timing.detect_ms = detected.batch.detect_ms
    message.timing.solve_ms = solution.solve_ms
    message.timing.total_ms = total_ms
    return message


@dataclass
class CameraPublishers:
    observation: Any
    robot_pose: Any
    robot_pose_valid: Any
    robot_pose_method: Any
    robot_pose_reprojection_error_px: Any
    robot_pose_tag_count: Any
    robot_pose_average_tag_distance_m: Any
    robot_pose_distortion_factor_px: Any
    calibration_provisional: Any
    state: Any
    applied_config_revision: Any
    applied_field_revision: Any
    last_consumed_sequence: Any
    fps_capture: Any
    fps_detect: Any
    latency_ms: Any
    temperature_c: Any
    error: Any
    drops: dict[str, Any] = field(default_factory=dict)


class NtPublisher:
    def __init__(self, nt_config: NtConfig, camera_ids: list[str]) -> None:
        self.enabled = nt_config.enabled
        self.instance = None
        self.publishers: dict[str, CameraPublishers] = {}
        self.global_publishers: list[Any] = []
        if not self.enabled:
            return
        try:
            import ntcore
            from wpimath.geometry import Pose3d
        except ImportError as exc:
            raise RuntimeError(
                "pyntcore and robotpy-wpimath are required when NT publishing is enabled"
            ) from exc
        self.ntcore = ntcore
        self.pose_type = Pose3d
        instance = ntcore.NetworkTableInstance.create()
        self.instance = instance
        if nt_config.mode == "server":
            instance.startServer("")
        else:
            if nt_config.server:
                instance.setServer(nt_config.server)
            else:
                instance.setServerTeam(int(nt_config.team))
            instance.startClient4(nt_config.identity)
        options = ntcore.PubSubOptions(keepDuplicates=True, sendAll=True, periodic=0.005)
        self.global_publishers = [
            instance.getIntegerTopic("/Spot/config/schema_version").publish(options),
            instance.getBooleanTopic("/Spot/config/enabled").publish(options),
        ]
        for camera_id in camera_ids:
            root = f"/Spot/{camera_id}"
            drops = {
                name: instance.getIntegerTopic(f"{root}/status/dropped_{name}").publish(options)
                for name in ("capture", "decode", "overwrite", "result_queue", "sequence")
            }
            self.publishers[camera_id] = CameraPublishers(
                observation=instance.getRawTopic(f"{root}/output/observations").publish(
                    "proto:spot.vision.v1.VisionFrame", options
                ),
                robot_pose=instance.getStructTopic(f"{root}/output/robot_pose", Pose3d).publish(
                    options
                ),
                robot_pose_valid=instance.getBooleanTopic(
                    f"{root}/output/robot_pose_valid"
                ).publish(options),
                robot_pose_method=instance.getStringTopic(
                    f"{root}/output/robot_pose_method"
                ).publish(options),
                robot_pose_reprojection_error_px=instance.getDoubleTopic(
                    f"{root}/output/robot_pose_reprojection_error_px"
                ).publish(options),
                robot_pose_tag_count=instance.getIntegerTopic(
                    f"{root}/output/robot_pose_tag_count"
                ).publish(options),
                robot_pose_average_tag_distance_m=instance.getDoubleTopic(
                    f"{root}/output/robot_pose_average_tag_distance_m"
                ).publish(options),
                robot_pose_distortion_factor_px=instance.getDoubleTopic(
                    f"{root}/output/robot_pose_distortion_factor_px"
                ).publish(options),
                calibration_provisional=instance.getBooleanTopic(
                    f"{root}/status/calibration_provisional"
                ).publish(options),
                state=instance.getStringTopic(f"{root}/status/state").publish(options),
                applied_config_revision=instance.getIntegerTopic(
                    f"{root}/status/applied_config_revision"
                ).publish(options),
                applied_field_revision=instance.getIntegerTopic(
                    f"{root}/status/applied_field_revision"
                ).publish(options),
                last_consumed_sequence=instance.getIntegerTopic(
                    f"{root}/status/last_consumed_sequence"
                ).publish(options),
                fps_capture=instance.getDoubleTopic(f"{root}/status/fps_capture").publish(options),
                fps_detect=instance.getDoubleTopic(f"{root}/status/fps_detect").publish(options),
                latency_ms=instance.getDoubleTopic(f"{root}/status/latency_ms").publish(options),
                temperature_c=instance.getDoubleTopic(f"{root}/status/temperature_c").publish(
                    options
                ),
                error=instance.getStringTopic(f"{root}/status/error").publish(options),
                drops=drops,
            )

    def publish_global(self, schema_version: int) -> None:
        if not self.enabled:
            return
        self.global_publishers[0].set(schema_version)
        self.global_publishers[1].set(True)

    def publish_calibration_status(self, camera: CameraConfig, provisional: bool) -> None:
        if not self.enabled:
            return
        self.publishers[camera.id].calibration_provisional.set(provisional)

    def publish_frame(
        self,
        camera: CameraConfig,
        field_revision: int,
        message: vision_pb2.VisionFrame,
        capture_timestamp_us: int,
        counters: CameraCounters,
        temperature_c: float,
        robot_pose: PoseCandidate | None = None,
    ) -> None:
        if not self.enabled:
            return
        publishers = self.publishers[camera.id]
        publishers.observation.set(message.SerializeToString(), capture_timestamp_us)
        if robot_pose is None:
            publishers.robot_pose_valid.set(False, capture_timestamp_us)
            publishers.robot_pose_method.set("METHOD_UNKNOWN", capture_timestamp_us)
            publishers.robot_pose_reprojection_error_px.set(0.0, capture_timestamp_us)
            publishers.robot_pose_tag_count.set(0, capture_timestamp_us)
        else:
            try:
                from wpimath.geometry import Pose3d, Quaternion, Rotation3d, Translation3d

                typed_pose = Pose3d(
                    Translation3d(*robot_pose.translation),
                    Rotation3d(Quaternion(*robot_pose.quaternion_wxyz)),
                )
                publishers.robot_pose.set(typed_pose, capture_timestamp_us)
                publishers.robot_pose_valid.set(True, capture_timestamp_us)
                publishers.robot_pose_method.set(
                    _POSE_METHOD_NAMES.get(int(robot_pose.method), "METHOD_UNKNOWN"),
                    capture_timestamp_us,
                )
                publishers.robot_pose_reprojection_error_px.set(
                    robot_pose.reprojection_error_px, capture_timestamp_us
                )
                publishers.robot_pose_tag_count.set(len(robot_pose.tag_ids), capture_timestamp_us)
            except Exception:  # pragma: no cover - runtime library/backend failures
                LOGGER.exception("failed to publish typed robot pose for %s", camera.id)
                publishers.robot_pose_valid.set(False, capture_timestamp_us)
                publishers.robot_pose_method.set("METHOD_UNKNOWN", capture_timestamp_us)
                publishers.robot_pose_reprojection_error_px.set(0.0, capture_timestamp_us)
                publishers.robot_pose_tag_count.set(0, capture_timestamp_us)
        publishers.robot_pose_average_tag_distance_m.set(
            robot_pose.average_tag_distance_m if robot_pose is not None else 0.0,
            capture_timestamp_us,
        )
        publishers.robot_pose_distortion_factor_px.set(
            robot_pose.distortion_factor_px if robot_pose is not None else 0.0, capture_timestamp_us
        )
        publishers.state.set(counters.state.value)
        publishers.applied_config_revision.set(camera.config_revision)
        publishers.applied_field_revision.set(field_revision)
        publishers.last_consumed_sequence.set(message.sequence)
        publishers.fps_capture.set(counters.fps_capture)
        publishers.fps_detect.set(counters.fps_detect)
        publishers.latency_ms.set(message.timing.total_ms)
        publishers.temperature_c.set(temperature_c)
        publishers.error.set(counters.error)
        publishers.drops["capture"].set(counters.capture_failures)
        publishers.drops["decode"].set(counters.decode_failures)
        publishers.drops["overwrite"].set(counters.overwritten_before_processing)
        publishers.drops["result_queue"].set(counters.result_queue_drops)
        publishers.drops["sequence"].set(counters.driver_sequence_gaps)

    def close(self) -> None:
        if self.instance is None:
            return
        try:
            self.instance.stopClient()
            self.instance.stopServer()
        finally:
            self.ntcore.NetworkTableInstance.destroy(self.instance)
            self.instance = None


class MemoryPublisher:
    """Test/replay publisher that retains the serialized transport contract."""

    def __init__(self) -> None:
        self.frames: list[tuple[str, bytes, int]] = []
        self.robot_poses: list[tuple[str, PoseCandidate | None, int]] = []

    def publish_global(self, schema_version: int) -> None:
        self.schema_version = schema_version

    def publish_calibration_status(self, camera: CameraConfig, provisional: bool) -> None:
        del camera
        self.calibration_provisional = provisional

    def publish_frame(
        self,
        camera: CameraConfig,
        field_revision: int,
        message: vision_pb2.VisionFrame,
        capture_timestamp_us: int,
        counters: CameraCounters,
        temperature_c: float,
        robot_pose: PoseCandidate | None = None,
    ) -> None:
        self.frames.append((camera.id, message.SerializeToString(), capture_timestamp_us))
        self.robot_poses.append((camera.id, robot_pose, capture_timestamp_us))

    def close(self) -> None:
        pass
