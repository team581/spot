package frc.robot.localization;

import edu.wpi.first.math.estimator.DifferentialDrivePoseEstimator;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.geometry.Rotation2d;
import edu.wpi.first.math.kinematics.DifferentialDriveKinematics;
import frc.robot.vision.TrustFactor;
import frc.robot.vision.Vision;
import frc.robot.vision.VisionProcessor;
import frc.robot.vision.results.VisionMeasurement;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.function.Consumer;

/** Offseason ingestion/trust flow with a stationary WPILib estimator replacing CTRE hardware. */
public final class Localization implements Vision.CaptureSource {
  private final DifferentialDrivePoseEstimator estimator;
  private final TrustFactor trust = new TrustFactor();
  private double first = Double.NaN;
  private double latest = Double.NaN;
  private long consumed;
  private long rejected;

  public Localization(Pose2d seed, double now) {
    // Track width is irrelevant: both bench wheel distances always remain zero.
    estimator = new DifferentialDrivePoseEstimator(new DifferentialDriveKinematics(.5),
        Rotation2d.kZero, 0, 0, seed);
    trust.reset(now, false);
  }

  public void updateOdometry(double now) {
    if (!Double.isFinite(now) || (Double.isFinite(latest) && now <= latest)) return;
    trust.updateOdometry(0, Double.isFinite(latest) ? now - latest : 0, false);
    estimator.updateWithTime(now, Rotation2d.kZero, 0, 0);
    if (!Double.isFinite(first)) first = now;
    latest = now;
  }

  public List<VisionMeasurement> ingest(Vision vision, double now) {
    return ingest(vision, now, value -> {});
  }

  public List<VisionMeasurement> ingest(
      Vision vision, double now, Consumer<VisionMeasurement> onConsumed) {
    var eligible = new ArrayList<VisionMeasurement>();
    // Check the whole batch against history before any correction changes it.
    for (var value : vision.drainMeasurements()) {
      if (vision.eligible(value, now) && poseAt(value.timestamp()).isPresent()) eligible.add(value);
      else rejected++;
    }
    for (var value : eligible) {
      // WPILib uses FPGA seconds directly; there is no CTRE clock in this project.
      estimator.addVisionMeasurement(value.pose(), value.timestamp(), value.standardDevs());
      onConsumed.accept(value);
      vision.measurementFused(value);
      trust.ingest(List.of(value));
      consumed++;
    }
    return List.copyOf(eligible);
  }

  public void reset(Pose2d pose, double now, Vision vision) {
    estimator.resetPosition(Rotation2d.kZero, 0, 0, pose);
    first = latest = Double.NaN;
    vision.reset(now);
    trust.reset(now, false);
    updateOdometry(now);
  }

  public Pose2d getPose() { return estimator.getEstimatedPosition(); }
  public TrustFactor trust() { return trust; }
  public long consumed() { return consumed; }
  public long rejected() { return rejected; }

  @Override public VisionProcessor.CaptureState current(double now) {
    return new VisionProcessor.CaptureState(getPose(), 0, 0, 0, 0, 0);
  }

  @Override public Optional<Pose2d> poseAt(double timestamp) {
    // WPILib sampleAt clamps outside history. Explicit bounds preserve the Spot contract.
    if (!Double.isFinite(timestamp) || !Double.isFinite(first) || timestamp < first
        || timestamp > latest || latest - timestamp > 1.5) return Optional.empty();
    return estimator.sampleAt(timestamp);
  }
}
