// Move to shared folder after offseason
package frc.robot.vision;

import edu.wpi.first.apriltag.AprilTagFieldLayout;
import edu.wpi.first.math.geometry.*;
import frc.robot.vision.data.*;
import java.lang.reflect.InvocationTargetException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;

/** Robot-owned profile values and their ordered content fingerprint. */
public final class SpotProtocol {
  public static byte[] digest(Object value) {
    try {
      var digest = MessageDigest.getInstance("SHA-256");
      update(digest, value);
      return digest.digest();
    } catch (NoSuchAlgorithmException exception) {
      throw new IllegalStateException(exception);
    }
  }

  public static long[] frameContext(Acknowledgement ack, String camera) {
    try {
      var digest = MessageDigest.getInstance("SHA-256");
      update(digest, ack);
      digest.update(camera.getBytes(StandardCharsets.UTF_8));
      var buffer = ByteBuffer.wrap(digest.digest()).order(ByteOrder.LITTLE_ENDIAN);
      return new long[] {buffer.getLong(), buffer.getLong()};
    } catch (NoSuchAlgorithmException exception) {
      throw new IllegalStateException(exception);
    }
  }

  public static String hash(Object value) {
    return HexFormat.of().formatHex(digest(value));
  }

  public static Pose3d pose(Pose value) {
    return new Pose3d(
        new Translation3d(value.xM(), value.yM(), value.zM()),
        new Rotation3d(new Quaternion(value.qw(), value.qx(), value.qy(), value.qz())));
  }

  public static Pose pose(Pose3d value) {
    var q = value.getRotation().getQuaternion();
    return new Pose(
        value.getX(), value.getY(), value.getZ(), q.getW(), q.getX(), q.getY(), q.getZ());
  }

  public static Profile profile(String robotId, AprilTagFieldLayout layout, double tagSizeM) {
    var tags =
        layout.getTags().stream()
            .sorted(java.util.Comparator.comparingInt(t -> t.ID))
            .map(t -> new FieldTag(t.ID, pose(t.pose), tagSizeM))
            .toList();
    return new Profile(
        robotId,
        List.of(),
        new FieldLayout("blue-wall-right", layout.getFieldLength(), layout.getFieldWidth(), tags),
        false,
        false,
        false,
        .25,
        .005,
        .02);
  }

  public static List<Integer> tagIds(long mask, FieldLayout layout) {
    if (layout.tags().size() > 64
        || (layout.tags().size() < 64 && (mask >>> layout.tags().size()) != 0))
      throw new IllegalArgumentException("Tag mask exceeds field layout");
    var ids = new java.util.ArrayList<Integer>();
    for (int i = 0; i < layout.tags().size(); i++)
      if ((mask & (1L << i)) != 0) ids.add(layout.tags().get(i).id());
    return List.copyOf(ids);
  }

  public static long tagMask(List<Integer> ids, FieldLayout layout) {
    long mask = 0;
    for (int id : ids) {
      int index = -1;
      for (int i = 0; i < layout.tags().size(); i++)
        if (layout.tags().get(i).id() == id) {
          index = i;
          break;
        }
      if (index < 0 || index >= 64)
        throw new IllegalArgumentException("Tag absent from field layout");
      mask |= 1L << index;
    }
    return mask;
  }

  public static long[] token(String text) {
    try {
      var bytes =
          MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
      var buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
      return new long[] {buffer.getLong(), buffer.getLong()};
    } catch (NoSuchAlgorithmException exception) {
      throw new IllegalStateException(exception);
    }
  }

  // Used once per profile or acknowledgement, never for per-frame decoding.
  private static void update(MessageDigest digest, Object value) {
    if (value instanceof Pose pose) {
      // Match WPILib geometry normalization when fingerprinting a profile.
      for (double coordinate : new double[] {pose.xM(), pose.yM(), pose.zM()})
        update(digest, coordinate);
      for (double q : new double[] {pose.qw(), pose.qx(), pose.qy(), pose.qz()})
        update(digest, Math.rint(q * 1e12) / 1e12);
    } else if (value instanceof Record record) {
      for (var component : record.getClass().getRecordComponents()) {
        try {
          update(digest, component.getAccessor().invoke(record));
        } catch (IllegalAccessException | InvocationTargetException exception) {
          throw new IllegalStateException(exception);
        }
      }
    } else if (value instanceof List<?> values) {
      digest.update(
          ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(values.size()).array());
      for (var item : values) update(digest, item);
    } else if (value instanceof String text) {
      var bytes = text.getBytes(StandardCharsets.UTF_8);
      digest.update(
          ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(bytes.length).array());
      digest.update(bytes);
    } else if (value instanceof Boolean flag) {
      digest.update((byte) (flag ? 1 : 0));
    } else {
      var buffer = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
      if (value instanceof Double number) buffer.putDouble(number);
      else buffer.putLong(((Number) value).longValue());
      digest.update(buffer.array());
    }
  }

  private SpotProtocol() {}
}
