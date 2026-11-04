package frc.robot.vision;

import edu.wpi.first.networktables.*;
import frc.robot.vision.data.*;
import frc.robot.vision.structs.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.*;

/** Desktop test peer standing in for Spot; production Java only subscribes to results. */
final class TestPeer implements AutoCloseable {
  private static String snake(String name) {
    return name.replaceAll("([a-z])([A-Z])", "$1_$2").toLowerCase(Locale.ROOT);
  }

  static byte[] frame(Observation observation, Acknowledgement ack, Profile profile) {
    var context = SpotProtocol.frameContext(ack, observation.cameraName());
    var capture = SpotProtocol.token(observation.captureEpoch());
    var estimates =
        new PoseEstimate[] {
          new PoseEstimate(edu.wpi.first.math.geometry.Pose3d.kZero, 0, 0, 0, 0, 0, 0, 0),
          new PoseEstimate(edu.wpi.first.math.geometry.Pose3d.kZero, 0, 0, 0, 0, 0, 0, 0)
        };
    for (int i = 0; i < observation.candidates().size(); i++) {
      var c = observation.candidates().get(i);
      estimates[i] =
          new PoseEstimate(
              SpotProtocol.pose(c.fieldToCamera()),
              c.method().ordinal(),
              SpotProtocol.tagMask(c.tagIds(), profile.field()),
              c.reprojectionErrorPx(),
              c.averageTagDistanceM(),
              c.imageAreaFraction(),
              c.imageSpreadFraction(),
              c.distortionDisplacementPx());
    }
    var t = observation.timing();
    var value =
        new FrameResult(
            context[0],
            context[1],
            capture[0],
            capture[1],
            observation.sequence(),
            observation.tagSelectionGeneration(),
            observation.captureLocalNtUs(),
            1,
            observation.timestampUncertaintyS(),
            SpotProtocol.tagMask(
                observation.tags().stream().map(TagObservation::id).toList(), profile.field()),
            observation.candidates().size(),
            estimates[0],
            estimates[1],
            t.captureToDetectMs(),
            t.detectMs(),
            t.solveMs(),
            t.totalMs());
    var bytes = ByteBuffer.allocate(FrameResult.struct.getSize()).order(ByteOrder.LITTLE_ENDIAN);
    FrameResult.struct.pack(bytes, value);
    return bytes.array();
  }

  private final NetworkTableInstance nt;

  private final List<AutoCloseable> resources = new ArrayList<>();

  TestPeer(NetworkTableInstance nt) {
    this.nt = nt;
  }

  public void close() throws Exception {
    for (var resource : resources) resource.close();
  }

  private void put(String path, Object value) {
    String key = "/Spot/config/acknowledgement/" + path;
    if (value instanceof String s) {
      var p = nt.getStringTopic(key).publish();
      p.set(s);
      resources.add(p);
    } else if (value instanceof Boolean b) {
      var p = nt.getBooleanTopic(key).publish();
      p.set(b);
      resources.add(p);
    } else {
      var p = nt.getIntegerTopic(key).publish();
      p.set(((Number) value).longValue());
      resources.add(p);
    }
  }

  void acknowledgement(Acknowledgement ack) throws ReflectiveOperationException {
    for (var field : Acknowledgement.class.getRecordComponents()) {
      if (!field.getName().equals("cameras"))
        put(snake(field.getName()), field.getAccessor().invoke(ack));
    }
    for (var camera : ack.cameras()) {
      for (var field : CameraGeneration.class.getRecordComponents()) {
        put(
            "cameras/" + camera.cameraName() + "/" + snake(field.getName()),
            field.getAccessor().invoke(camera));
      }
    }
    var names = nt.getStringArrayTopic("/Spot/config/acknowledgement/camera_names").publish();
    names.set(ack.cameras().stream().map(CameraGeneration::cameraName).toArray(String[]::new));
    resources.add(names);
    var header = nt.getStringTopic("/Spot/config/ack").publish();
    header.set(SpotProtocol.hash(ack));
    resources.add(header);
  }
}
