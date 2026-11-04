// Move to shared folder after offseason
package frc.robot.vision;

import static java.util.Comparator.comparingInt;

import edu.wpi.first.apriltag.AprilTagFieldLayout;
import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.math.geometry.Quaternion;
import edu.wpi.first.math.geometry.Rotation3d;
import edu.wpi.first.math.geometry.Transform3d;
import edu.wpi.first.math.geometry.Translation3d;
import frc.robot.vision.generated.SpotProtos;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/** Complete protobuf settings as code; physical selectors and intrinsics live on Spot. */
public final class SpotProtocol {
  public static SpotProtos.CameraDefinition.Builder camera(String name, Transform3d measuredMount) {
    return SpotProtos.CameraDefinition.newBuilder()
        .setName(name)
        .setEnabled(true)
        .setRobotToCamera(pose(new Pose3d().transformBy(measuredMount)));
  }

  public static String hash(com.google.protobuf.MessageLite message) {
    try {
      return HexFormat.of()
          .formatHex(MessageDigest.getInstance("SHA-256").digest(message.toByteArray()));
    } catch (NoSuchAlgorithmException exception) {
      throw new IllegalStateException(exception);
    }
  }

  public static SpotProtos.ControlPolicy pinned(String name, double value, boolean required) {
    return SpotProtos.ControlPolicy.newBuilder()
        .setName(name)
        .setDefaultValue(value)
        .setRequired(required)
        .build();
  }

  public static SpotProtos.Pose pose(Pose3d pose) {
    var q = pose.getRotation().getQuaternion();
    return SpotProtos.Pose.newBuilder()
        .setXM(pose.getX())
        .setYM(pose.getY())
        .setZM(pose.getZ())
        .setQw(q.getW())
        .setQx(q.getX())
        .setQy(q.getY())
        .setQz(q.getZ())
        .build();
  }

  public static Pose3d pose(SpotProtos.Pose pose) {
    return new Pose3d(
        new Translation3d(pose.getXM(), pose.getYM(), pose.getZM()),
        new Rotation3d(new Quaternion(pose.getQw(), pose.getQx(), pose.getQy(), pose.getQz())));
  }

  public static SpotProtos.Profile.Builder profile(
      String robotId, AprilTagFieldLayout layout, double tagSizeM) {
    var field =
        SpotProtos.FieldLayout.newBuilder()
            .setOrigin("blue-wall-right")
            .setLengthM(layout.getFieldLength())
            .setWidthM(layout.getFieldWidth());
    // Stable ascending IDs produce the same profile hash across restarts.
    layout.getTags().stream()
        .sorted(comparingInt(tag -> tag.ID))
        .forEach(
            tag ->
                field.addTags(
                    SpotProtos.FieldTag.newBuilder()
                        .setId(tag.ID)
                        .setFieldToTag(pose(tag.pose))
                        .setSizeM(tagSizeM)));
    return SpotProtos.Profile.newBuilder()
        .setSchemaVersion(2)
        .setRobotId(robotId)
        .setField(field)
        .setMaxAgeS(.25)
        .setFutureToleranceS(.005)
        .setReorderWindowS(.02);
  }

  public static SpotProtos.ControlPolicy tuning(String name, double defaultValue) {
    return SpotProtos.ControlPolicy.newBuilder()
        .setName(name)
        .setDefaultValue(defaultValue)
        .setAllowOverride(true)
        .build();
  }

  private SpotProtocol() {}
}
