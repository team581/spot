// Move to shared folder after offseason
package frc.robot.vision;

import frc.robot.vision.data.*;
import frc.robot.vision.results.VisionMeasurement;
import java.util.List;

/** A single owned snapshot per control tick. Getters never poll transport. */
public interface VisionIO extends AutoCloseable {
  record Health(
      boolean available,
      String reason,
      Acknowledgement acknowledgement,
      frc.robot.vision.data.Health service) {
    public Health(boolean available, String reason, Acknowledgement acknowledgement) {
      this(
          available,
          reason,
          acknowledgement,
          new frc.robot.vision.data.Health(
              "", 0L, 0.0, "", 0L, 0.0, 0L, 0L, 0L, "", "", "", java.util.List.of()));
    }
  }

  record Inputs(Health health, List<Sample> samples) {
    public Inputs {
      samples = List.copyOf(samples);
    }
  }

  record Sample(
      Observation observation,
      double captureFpgaSeconds,
      frc.robot.vision.structs.FrameResult frame) {
    public Sample(Observation observation, double captureFpgaSeconds) {
      this(observation, captureFpgaSeconds, null);
    }
  }

  record TagSelection(long generation, List<Integer> allowedTagIds) {
    public TagSelection {
      allowedTagIds = List.copyOf(allowedTagIds);
      if (generation <= 0
          || !allowedTagIds.equals(allowedTagIds.stream().distinct().sorted().toList()))
        throw new IllegalArgumentException("positive generation and sorted unique IDs required");
    }
  }

  @Override
  default void close() {}

  default void measurementFused(VisionMeasurement measurement) {}

  default void publishDecisions(double now) {}

  Inputs readInputs(double nowFpgaSeconds, boolean robotEnabled);

  default void reportDecision(Sample sample, VisionProcessor.Decision decision) {}

  default void reset(double nowFpgaSeconds) {}

  default void setFusionEnabled(boolean enabled) {}

  default void setTagSelection(TagSelection selection) {}
}
