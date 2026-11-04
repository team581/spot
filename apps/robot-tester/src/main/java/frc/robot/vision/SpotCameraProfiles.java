package frc.robot.vision;

import edu.wpi.first.math.geometry.Transform3d;
import java.util.List;

/** Mount value type retained from offseason; settings live in VisionConfig.java. */
public final class SpotCameraProfiles {
  public record Camera(String name, Transform3d mount, VisionProcessor.Policy qualityPolicy) {
    public static Camera fixed(String name, Transform3d mount) {
      return new Camera(name, mount, null);
    }
  }
  public static final List<String> CAMERA_NAMES = List.of("left", "right", "front", "back");
  private SpotCameraProfiles() {}
}
