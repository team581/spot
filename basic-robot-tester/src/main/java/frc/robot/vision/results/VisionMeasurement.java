// Move to shared folder after offseason
package frc.robot.vision.results;

import static com.google.common.base.Preconditions.checkArgument;

import edu.wpi.first.math.VecBuilder;
import edu.wpi.first.math.Vector;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.numbers.N3;
import java.util.List;

/** Owned immutable data. Time is FPGA seconds; CTRE conversion belongs at ingestion. */
public record VisionMeasurement(
    String source,
    String frameId,
    Pose2d pose,
    double timestamp,
    double stdX,
    double stdY,
    double stdHeading,
    List<Integer> tagIds,
    double innovationM,
    double normalizedInnovation) {
  public VisionMeasurement {
    tagIds = List.copyOf(tagIds);
    checkArgument(
        source != null
            && frameId != null
            && pose != null
            && Double.isFinite(timestamp)
            && Double.isFinite(pose.getX())
            && Double.isFinite(pose.getY())
            && Double.isFinite(pose.getRotation().getRadians())
            && Double.isFinite(stdX)
            && Double.isFinite(stdY)
            && Double.isFinite(stdHeading)
            && stdX > 0
            && stdY > 0
            && stdHeading > 0
            && Double.isFinite(innovationM)
            && innovationM >= 0
            && Double.isFinite(normalizedInnovation)
            && normalizedInnovation >= 0,
        "finite pose/time and positive finite deviations required");
  }

  /** Returns a fresh vector; callers cannot modify a queued measurement. */
  public Vector<N3> standardDevs() {
    return VecBuilder.fill(stdX, stdY, stdHeading);
  }
}
