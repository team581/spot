// Move to shared folder after offseason
package frc.robot.vision.data;

import java.util.List;

public record TagObservation(
    int id,
    List<Double> cornersXyPx,
    int hamming,
    double decisionMargin,
    boolean usedForPose,
    String rejectionReason,
    Double distortionDisplacementPx) {
  public TagObservation {
    cornersXyPx = List.copyOf(cornersXyPx);
  }
}
