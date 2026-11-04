// Move to shared folder after offseason
package frc.robot.vision.data;

import java.util.List;

public record CameraDefinition(
    String name,
    boolean required,
    boolean enabled,
    Pose robotToCamera,
    int imageRotationDeg,
    List<OpticalMode> allowedModes,
    List<ControlPolicy> controls,
    boolean movingMount,
    String jointName) {
  public CameraDefinition {
    allowedModes = List.copyOf(allowedModes);
    controls = List.copyOf(controls);
  }
}
