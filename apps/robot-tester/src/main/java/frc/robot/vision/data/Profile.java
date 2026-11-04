// Move to shared folder after offseason
package frc.robot.vision.data;

import java.util.List;

public record Profile(
    String robotId,
    List<CameraDefinition> cameras,
    FieldLayout field,
    boolean fusionEnabled,
    boolean headingEnabled,
    boolean revisedTrustEnabled,
    double maxAgeS,
    double futureToleranceS,
    double reorderWindowS) {
  public Profile {
    cameras = List.copyOf(cameras);
  }
}
