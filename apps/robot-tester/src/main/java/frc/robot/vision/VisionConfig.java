package frc.robot.vision;

import edu.wpi.first.apriltag.AprilTagFieldLayout;
import edu.wpi.first.apriltag.AprilTagFields;
import edu.wpi.first.math.geometry.Rotation3d;
import edu.wpi.first.math.geometry.Transform3d;
import edu.wpi.first.math.geometry.Translation3d;
import frc.robot.vision.SpotCameraConfig.Control;
import frc.robot.vision.data.*;
import java.util.HashSet;
import java.util.List;

/** Student-editable vision settings, following the other subsystem Config classes. */
public final class VisionConfig {
  public static final String ROBOT_ID = "basic-robot-tester";
  // In this project fusion goes only to the stationary bench estimator.
  public static final boolean FUSION_ENABLED = false;
  public static final double TAG_SIZE_M = .1651;
  public static final AprilTagFieldLayout FIELD_LAYOUT =
      AprilTagFieldLayout.loadField(AprilTagFields.k2026RebuiltWelded);

  // Add named constants such as FRONT, LEFT, RIGHT and BACK, then list them in
  // CAMERAS.
  // Bench role labels only: these mounts are examples, not measured geometry.
  // Replace them before validating poses; fusion must remain disabled.
  public static final SpotCameraConfig FRONT =
      new SpotCameraConfig(
          "front",
          true,
          mount(.40, 0.2, .30, 0, -20, 0), // metres, then roll/pitch/yaw in degrees
          0, // image rotation: 0 or 180 degrees
          new CaptureSettings(640, 480, 120, PixelFormat.MJPEG),
          List.of(
              Control.pinned("auto_exposure", 1),
              Control.tunable("exposure_time_absolute", 5000),
              Control.tunable("gain", 64),
              Control.pinned("brightness", 0)));

  public static final SpotCameraConfig BACK =
      new SpotCameraConfig(
          "back",
          true,
          mount(-.40, 0.5, .30, 0, -20, 180), // metres, then roll/pitch/yaw in degrees
          0, // image rotation: 0 or 180 degrees
          new CaptureSettings(640, 480, 120, PixelFormat.MJPEG),
          List.of(
              Control.pinned("auto_exposure", 1),
              Control.tunable("exposure_time_absolute", 5000),
              Control.tunable("gain", 64),
              Control.pinned("brightness", 0)));

  // Zero transform is an explicit placeholder for the unmeasured third mount.
  public static final SpotCameraConfig SIDE =
      new SpotCameraConfig(
          "side",
          true,
          mount(0, 0, 0, 0, 0, 0),
          0,
          new CaptureSettings(640, 480, 120, PixelFormat.MJPEG),
          List.of(
              Control.pinned("auto_exposure", 1),
              Control.tunable("exposure_time_absolute", 6000),
              Control.tunable("gain", 61),
              Control.pinned("brightness", -21)));

  public static final List<SpotCameraConfig> CAMERAS = List.of(FRONT, BACK, SIDE);

  /** NWU: +X forward, +Y left, +Z up; right-handed roll, pitch, yaw in degrees. */
  public static Transform3d mount(
      double xM, double yM, double zM, double rollDeg, double pitchDeg, double yawDeg) {
    return new Transform3d(
        new Translation3d(xM, yM, zM),
        new Rotation3d(Math.toRadians(rollDeg), Math.toRadians(pitchDeg), Math.toRadians(yawDeg)));
  }

  public static List<SpotCameraProfiles.Camera> mounts() {
    return CAMERAS.stream()
        .map(camera -> SpotCameraProfiles.Camera.fixed(camera.name(), camera.robotToCamera()))
        .toList();
  }

  public static Profile profile() {
    return profile(CAMERAS);
  }

  static Profile profile(List<SpotCameraConfig> cameras) {
    SpotCameraConfig.identifier(ROBOT_ID);
    if (!Double.isFinite(TAG_SIZE_M) || TAG_SIZE_M <= 0 || TAG_SIZE_M > 1 || cameras.size() > 32)
      throw new IllegalArgumentException("invalid vision configuration");
    var names = new HashSet<String>();
    for (var camera : cameras) {
      if (!names.add(camera.name())) throw new IllegalArgumentException("duplicate camera name");
    }
    var defaults = SpotProtocol.profile(ROBOT_ID, FIELD_LAYOUT, TAG_SIZE_M);
    return new Profile(
        ROBOT_ID,
        cameras.stream().map(SpotCameraConfig::definition).toList(),
        defaults.field(),
        FUSION_ENABLED,
        false,
        true,
        defaults.maxAgeS(),
        defaults.futureToleranceS(),
        defaults.reorderWindowS());
  }

  private VisionConfig() {}
}
