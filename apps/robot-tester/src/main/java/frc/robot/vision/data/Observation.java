// Move to shared folder after offseason
package frc.robot.vision.data;

import java.util.List;

public record Observation(
    String robotId,
    String robotSession,
    String serviceSession,
    String captureEpoch,
    long connectionEpoch,
    long syncEpoch,
    long sequence,
    String cameraName,
    String bindingId,
    long bindingGeneration,
    String manifestHash,
    String fieldHash,
    String calibrationHash,
    boolean calibrationValid,
    String runtimeGeneration,
    String modeId,
    String opticalSignature,
    long captureLocalNtUs,
    String timestampSource,
    double timestampUncertaintyS,
    List<PoseCandidate> candidates,
    List<TagObservation> tags,
    ProcessingTiming timing,
    long tagSelectionGeneration) {
  public Observation {
    candidates = List.copyOf(candidates);
    tags = List.copyOf(tags);
  }
}
