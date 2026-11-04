// Move to shared folder after offseason
package frc.robot.vision.data;

import java.util.List;

public record Health(
    String serviceSession,
    long sequence,
    double uptimeS,
    String syncState,
    long offsetUs,
    double syncUpdateAgeS,
    long connectionEpoch,
    long syncEpoch,
    long discontinuities,
    String runtimeGeneration,
    String releaseId,
    String nativeHash,
    List<String> faults) {
  public Health {
    faults = List.copyOf(faults);
  }
}
