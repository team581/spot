package frc.robot.vision;

import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.wpilibj.DriverStation.Alliance;
import frc.robot.vision.generated.SpotProtos;
import java.util.List;
import java.util.Optional;
import java.util.function.BooleanSupplier;
import java.util.function.DoubleSupplier;
import java.util.function.Supplier;

/** Compiled offseason construction seam; configuration contains measured mounts and modes. */
final class SpotBetaRobotExample {
  static Vision create(
      NetworkTableInstance nt,
      String session,
      SpotProtos.Profile profile,
      List<SpotCameraProfiles.Camera> mounts,
      Vision.CaptureSource capture,
      DoubleSupplier clock,
      BooleanSupplier enabled,
      BooleanSupplier operatorVision,
      Supplier<Optional<Alliance>> alliance) {
    return new Vision(
        new SpotVisionIO(nt, profile, session),
        profile,
        mounts,
        capture,
        clock,
        enabled,
        operatorVision,
        alliance);
  }

  private SpotBetaRobotExample() {}
}
