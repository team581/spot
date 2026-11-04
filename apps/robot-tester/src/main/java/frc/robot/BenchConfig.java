package frc.robot;

import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.geometry.Rotation2d;
import frc.robot.vision.SpotCameraProfiles;
import frc.robot.vision.VisionConfig;
import frc.robot.vision.generated.SpotProtos;
import java.util.List;

/** Bench-only seed pose; shared vision settings are owned by VisionConfig. */
public record BenchConfig(
    SpotProtos.Profile profile, List<SpotCameraProfiles.Camera> mounts, Pose2d stationaryPose) {
  public static final Pose2d STATIONARY_POSE = new Pose2d(4, 4, Rotation2d.kZero);

  public BenchConfig { mounts = List.copyOf(mounts); }

  public static BenchConfig create() {
    return new BenchConfig(VisionConfig.profile(), VisionConfig.mounts(), STATIONARY_POSE);
  }
}
