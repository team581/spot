// Move to shared folder after offseason
package frc.robot.vision;

import edu.wpi.first.math.geometry.Transform3d;
import edu.wpi.first.networktables.*;
import frc.robot.vision.data.*;
import frc.robot.vision.structs.FieldTagValue;
import java.util.*;

/** Native NT values for slow-changing profile and acknowledgement metadata. */
final class SpotMetadata implements AutoCloseable {
  private final NetworkTableInstance nt;
  private final String root;
  private final Map<String, Subscriber> subscribers = new HashMap<>();
  private final List<AutoCloseable> resources = new ArrayList<>();
  private String lastDigest = "";
  private Acknowledgement lastAcknowledgement;

  SpotMetadata(NetworkTableInstance nt, String root) {
    this.nt = nt;
    this.root = root;
  }

  public void close() {
    for (var sub : subscribers.values()) sub.close();
    for (var resource : resources) {
      try {
        resource.close();
      } catch (Exception exception) {
        throw new IllegalStateException(exception);
      }
    }
  }

  private boolean flag(String path) {
    return ((BooleanSubscriber)
            subscribers.computeIfAbsent(path, p -> nt.getBooleanTopic(key(p)).subscribe(false)))
        .get();
  }

  private long integer(String path) {
    return ((IntegerSubscriber)
            subscribers.computeIfAbsent(path, p -> nt.getIntegerTopic(key(p)).subscribe(0)))
        .get();
  }

  private String key(String path) {
    return root + "/config/acknowledgement/" + path;
  }

  private void put(String path, Object value) {
    String key = root + "/robot/profile/" + path;
    if (value instanceof String text) {
      var pub = nt.getStringTopic(key).publish();
      pub.set(text);
      resources.add(pub);
    } else if (value instanceof String[] strings) {
      var pub = nt.getStringArrayTopic(key).publish();
      pub.set(strings);
      resources.add(pub);
    } else if (value instanceof Boolean flag) {
      var pub = nt.getBooleanTopic(key).publish();
      pub.set(flag);
      resources.add(pub);
    } else if (value instanceof Double number) {
      var pub = nt.getDoubleTopic(key).publish();
      pub.set(number);
      resources.add(pub);
    } else {
      var pub = nt.getIntegerTopic(key).publish();
      pub.set(((Number) value).longValue());
      resources.add(pub);
    }
  }

  private String[] strings(String path) {
    return ((StringArraySubscriber)
            subscribers.computeIfAbsent(
                path, p -> nt.getStringArrayTopic(key(p)).subscribe(new String[0])))
        .get();
  }

  private String text(String path) {
    return ((StringSubscriber)
            subscribers.computeIfAbsent(path, p -> nt.getStringTopic(key(p)).subscribe("")))
        .get();
  }

  Optional<Acknowledgement> acknowledgement(String digest) {
    if (digest.isEmpty()) return Optional.empty();
    if (digest.equals(lastDigest)) return Optional.of(lastAcknowledgement);
    var names = strings("camera_names");
    if (names.length > 32) return Optional.empty();
    var cameras = new ArrayList<CameraGeneration>();
    for (var name : names) {
      if (!name.matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")) return Optional.empty();
      String p = "cameras/" + name + "/";
      cameras.add(
          new CameraGeneration(
              text(p + "camera_name"),
              text(p + "binding_id"),
              integer(p + "binding_generation"),
              text(p + "calibration_hash"),
              text(p + "mode_id"),
              text(p + "optical_signature"),
              flag(p + "calibration_valid")));
    }
    var value =
        new Acknowledgement(
            text("robot_id"),
            text("robot_session"),
            text("manifest_hash"),
            text("service_session"),
            integer("connection_epoch"),
            integer("sync_epoch"),
            text("runtime_generation"),
            text("field_hash"),
            cameras,
            flag("applied"),
            text("error"),
            flag("tag_selection_supported"));
    if (!SpotProtocol.hash(value).equals(digest)) return Optional.empty();
    lastDigest = digest;
    lastAcknowledgement = value;
    return Optional.of(value);
  }

  void publish(Profile profile) {
    put("robot_id", profile.robotId());
    put("fusion_enabled", profile.fusionEnabled());
    put("heading_enabled", profile.headingEnabled());
    put("revised_trust_enabled", profile.revisedTrustEnabled());
    put("max_age_s", profile.maxAgeS());
    put("future_tolerance_s", profile.futureToleranceS());
    put("reorder_window_s", profile.reorderWindowS());
    put("field/origin", profile.field().origin());
    put("field/length_m", profile.field().lengthM());
    put("field/width_m", profile.field().widthM());
    var tags =
        nt.getStructArrayTopic(root + "/robot/profile/field/tags", FieldTagValue.struct).publish();
    tags.set(
        profile.field().tags().stream()
            .map(tag ->
                new FieldTagValue(tag.id(), SpotProtocol.pose(tag.fieldToTag()), tag.sizeM()))
            .toArray(FieldTagValue[]::new));
    resources.add(tags);
    for (var camera : profile.cameras()) {
      String p = "cameras/" + camera.name() + "/";
      put(p + "required", camera.required());
      put(p + "enabled", camera.enabled());
      put(p + "image_rotation_deg", camera.imageRotationDeg());
      put(p + "moving_mount", camera.movingMount());
      put(p + "joint_name", camera.jointName());
      var pose =
          nt.getStructTopic(root + "/robot/profile/" + p + "robot_to_camera", Transform3d.struct)
              .publish();
      pose.set(
          new Transform3d(
              edu.wpi.first.math.geometry.Pose3d.kZero, SpotProtocol.pose(camera.robotToCamera())));
      resources.add(pose);
      for (var mode : camera.allowedModes()) {
        String m = p + "modes/" + mode.id() + "/";
        put(m + "width", mode.width());
        put(m + "height", mode.height());
        put(m + "fps", mode.fps());
        put(m + "pixel_format", mode.pixelFormat());
        put(m + "optical_signature", mode.opticalSignature());
      }
      put(p + "modes", camera.allowedModes().stream().map(OpticalMode::id).toArray(String[]::new));
      for (var control : camera.controls()) {
        String c = p + "controls/" + control.name() + "/";
        put(c + "default_value", control.defaultValue());
        put(c + "allow_override", control.allowOverride());
        put(c + "required", control.required());
      }
      put(
          p + "controls",
          camera.controls().stream().map(ControlPolicy::name).toArray(String[]::new));
    }
    put("cameras", profile.cameras().stream().map(CameraDefinition::name).toArray(String[]::new));
  }
}
