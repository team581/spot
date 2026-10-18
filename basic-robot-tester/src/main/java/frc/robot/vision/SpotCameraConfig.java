package frc.robot.vision;

import edu.wpi.first.math.geometry.Transform3d;
import frc.robot.vision.generated.SpotProtos;
import java.util.HashSet;
import java.util.List;

/** Robot-owned settings. USB bindings and calibration stay on the Jetson. */
public record SpotCameraConfig(
    String name,
    boolean required,
    Transform3d robotToCamera,
    int imageRotationDeg,
    CaptureSettings capture,
    List<Control> controls) {
  public SpotCameraConfig {
    identifier(name);
    require(robotToCamera != null, "measured mount required");
    for (double value :
        new double[] {
          robotToCamera.getX(),
          robotToCamera.getY(),
          robotToCamera.getZ(),
          robotToCamera.getRotation().getX(),
          robotToCamera.getRotation().getY(),
          robotToCamera.getRotation().getZ()
        }) {
      require(Double.isFinite(value), "finite mount required");
    }
    require(imageRotationDeg == 0 || imageRotationDeg == 180, "image rotation must be 0 or 180");
    require(capture != null, "capture settings required");
    controls = List.copyOf(controls);
    require(controls.size() <= 64, "at most 64 controls allowed");
    var controlNames = new HashSet<String>();
    for (var control : controls)
      require(controlNames.add(control.name()), "duplicate control name");
  }

  public record Control(String name, double value, boolean required, boolean allowOverride) {
    public Control {
      identifier(name);
      require(Double.isFinite(value), "finite control value required");
    }

    /** Robot code owns this required control; the GUI cannot override it. */
    public static Control pinned(String name, double value) {
      return new Control(name, value, true, false);
    }

    /** Required control with a robot default and an allowed saved GUI override. */
    public static Control tunable(String name, double defaultValue) {
      return new Control(name, defaultValue, true, true);
    }

    private SpotProtos.ControlPolicy toProto() {
      return SpotProtos.ControlPolicy.newBuilder()
          .setName(name)
          .setDefaultValue(value)
          .setRequired(required)
          .setAllowOverride(allowOverride)
          .build();
    }
  }

  public SpotProtos.CameraDefinition definition() {
    return SpotProtocol.camera(name, robotToCamera)
        .setRequired(required)
        .setImageRotationDeg(imageRotationDeg)
        .addAllowedModes(capture.toProto())
        .addAllControls(controls.stream().map(Control::toProto).toList())
        .build();
  }

  static void identifier(String value) {
    require(
        value != null && value.matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"), "invalid identifier");
  }

  private static void require(boolean condition, String message) {
    if (!condition) throw new IllegalArgumentException(message);
  }
}
