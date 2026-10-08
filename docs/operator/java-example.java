package com.team581.vision;

import com.team581.vision.proto.SpotProtos;
import edu.wpi.first.apriltag.AprilTagFieldLayout;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.geometry.Transform3d;
import edu.wpi.first.networktables.NetworkTableInstance;
import java.util.List;
import java.util.Optional;
import java.util.function.DoubleFunction;

/** Compiled documentation example; mounts/modes are supplied from real measurements. */
final class SpotBetaRobotExample {
  record Integration(VisionPipeline vision, CaptureHistory history, SpotProtos.Profile profile) {}

  static Integration create(
      String robotId,
      AprilTagFieldLayout blueOriginField,
      double measuredTagSizeM,
      Transform3d measuredMount,
      SpotProtos.OpticalMode verifiedMode,
      DoubleFunction<Optional<Pose2d>> capturePoseAt,
      NetworkTableInstance robotNtServer) {
    var profile =
        VisionProfiles.profile(robotId, blueOriginField, measuredTagSizeM)
            .addCameras(
                VisionProfiles.camera("front", measuredMount)
                    .setRequired(true)
                    .addAllowedModes(verifiedMode))
            .setFusionEnabled(false)
            .setHeadingEnabled(false)
            .setRevisedTrustEnabled(false)
            .build();
    var history = new CaptureHistory(capturePoseAt);
    // Add current FPGA-time pose/motion/tilt to history each robot loop before collect().
    var processor =
        new VisionProcessor(
            profile,
            List.of(VisionCamera.fixed("front", measuredMount)),
            history,
            VisionProcessor.Policy.conservative());
    var vision =
        new VisionPipeline(
            new SpotVisionIO(robotNtServer, profile),
            profile,
            processor,
            List.of(),
            new VisionDiagnostics());
    return new Integration(vision, history, profile);
  }
}
