// Move to shared folder after offseason
package frc.robot.vision;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.collect.ImmutableList;
import com.google.protobuf.InvalidProtocolBufferException;
import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.networktables.PubSubOption;
import edu.wpi.first.networktables.RawPublisher;
import edu.wpi.first.networktables.RawSubscriber;
import edu.wpi.first.networktables.StringPublisher;
import edu.wpi.first.networktables.TimestampedRaw;
import frc.robot.vision.generated.SpotProtos;
import frc.robot.vision.results.VisionMeasurement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.OptionalDouble;

/** NT4 robot server adapter; transport bytes and metadata stay atomic. */
public final class SpotVisionIO implements VisionIO {
  public static final String ROOT = "/Spot/v2";
  // A reconnect needs a newly timestamped profile; cached authority stays invalid.
  private static final double MANIFEST_PERIOD_S = .1;
  private static final ObjectMapper JSON = new ObjectMapper();

  /**
   * On the verified roboRIO NT server both clock domains use the FPGA epoch. Local-value serverTime
   * sentinels 0/1 use the server-local timestamp. Conflicting domains are rejected. Real roboRIO
   * qualification is still required.
   */
  public static OptionalDouble captureTimestamp(TimestampedRaw sample, boolean onRobotServer) {
    if (!onRobotServer || sample.timestamp <= 1 || sample.serverTime < 0) {
      return OptionalDouble.empty();
    }
    if (sample.serverTime > 1 && Math.abs(sample.timestamp - sample.serverTime) > 1000) {
      return OptionalDouble.empty();
    }
    long timestamp = sample.serverTime > 1 ? sample.serverTime : sample.timestamp;
    return OptionalDouble.of(timestamp / 1e6);
  }

  static void markDecisionFused(Map<String, Object> values, String frameId) {
    if (values != null && frameId.equals(values.get("frame_id"))) {
      values.put("fused", true);
    }
  }

  private final NetworkTableInstance instance;
  private final SpotProtos.Manifest manifest;
  private final RawPublisher manifestPublisher;
  private final RawPublisher statePublisher;
  private final RawSubscriber ackSubscriber;
  private final RawSubscriber healthSubscriber;
  private final StringPublisher decisionsPublisher;
  private final Map<String, Map<String, Object>> decisions = new HashMap<>();
  private double lastDecisionPublish = Double.NEGATIVE_INFINITY;
  private final Map<String, RawSubscriber> cameras = new HashMap<>();
  private SpotProtos.Acknowledgement acknowledgement =
      SpotProtos.Acknowledgement.getDefaultInstance();
  private SpotProtos.Health lastHealth = SpotProtos.Health.getDefaultInstance();
  private double lastHealthTimestamp = Double.NEGATIVE_INFINITY;
  private double lastPublish = Double.NEGATIVE_INFINITY;
  private double resetTimestamp = Double.NEGATIVE_INFINITY;
  private long stateSequence;

  private long malformed;

  private String generation = "";
  private TagSelection selection;
  private boolean effectiveFusion;
  private boolean closed;

  public SpotVisionIO(NetworkTableInstance instance, SpotProtos.Profile profile, String session) {
    this.instance = instance;
    this.manifest =
        SpotProtos.Manifest.newBuilder()
            .setProfile(profile)
            .setRobotSession(session)
            .setManifestHash(SpotProtocol.hash(profile))
            .build();
    manifestPublisher =
        instance
            .getRawTopic(ROOT + "/robot/manifest")
            .publish(
                "proto:spot.vision.v2.Manifest",
                PubSubOption.sendAll(true),
                PubSubOption.keepDuplicates(true),
                PubSubOption.periodic(.02));
    statePublisher =
        instance
            .getRawTopic(ROOT + "/robot/state")
            .publish(
                "proto:spot.vision.v2.RobotState",
                PubSubOption.sendAll(true),
                PubSubOption.keepDuplicates(true),
                PubSubOption.periodic(.02));
    ackSubscriber = subscribe(ROOT + "/config/ack", "Acknowledgement", 16);
    healthSubscriber = subscribe(ROOT + "/health", "Health", 16);
    decisionsPublisher =
        instance.getStringTopic(ROOT + "/robot/decisions").publish(PubSubOption.periodic(1.0));
    for (var camera : profile.getCamerasList()) {
      cameras.put(
          camera.getName(),
          subscribe(ROOT + "/" + camera.getName() + "/observations", "Observation", 16));
    }
  }

  @Override
  public void close() {
    if (closed) return;
    closed = true;
    decisionsPublisher.close();
    manifestPublisher.close();
    statePublisher.close();
    ackSubscriber.close();
    healthSubscriber.close();
    for (var camera : cameras.values()) {
      camera.close();
    }
  }

  public long malformedCount() {
    return malformed;
  }

  public SpotProtos.Manifest manifest() {
    return manifest;
  }

  @Override
  public void measurementFused(VisionMeasurement measurement) {
    markDecisionFused(decisions.get(measurement.source()), measurement.frameId());
  }

  @Override
  public void publishDecisions(double now) {
    if (now - lastDecisionPublish < 1.) {
      return;
    }
    lastDecisionPublish = now;
    try {
      var fresh = new HashMap<String, Map<String, Object>>();
      if (health(now).available()) {
        for (var entry : decisions.entrySet()) {
          var values = entry.getValue();
          double captured = (double) values.get("capture_fpga_s");
          if (now - captured <= .5
              && captured <= now + .005
              && acknowledgement.getRuntimeGeneration().equals(values.get("runtime_generation"))
              && acknowledgement.getServiceSession().equals(values.get("service_session"))
              && selection != null
              && Long.valueOf(selection.generation())
                  .equals(values.get("tag_selection_generation"))) {
            fresh.put(entry.getKey(), values);
          }
        }
      }
      decisionsPublisher.set(
          JSON.writeValueAsString(
              Map.of(
                  "robot_session",
                  manifest.getRobotSession(),
                  "manifest_hash",
                  manifest.getManifestHash(),
                  "fusion_enabled",
                  effectiveFusion,
                  "heading_enabled",
                  manifest.getProfile().getHeadingEnabled(),
                  "revised_trust_enabled",
                  manifest.getProfile().getRevisedTrustEnabled(),
                  "cameras",
                  fresh)));
    } catch (java.io.IOException exception) {
      malformed++;
    }
  }

  @Override
  public Inputs readInputs(double now, boolean robotEnabled) {
    update(now, robotEnabled);
    var result = new ArrayList<Sample>();
    var health = health(now);
    for (var camera : cameras.entrySet()) {
      for (var sample : camera.getValue().readQueue()) {
        if (!health.available() || sample.value.length > 65536) {
          continue;
        }
        try {
          var observation = SpotProtos.Observation.parseFrom(sample.value);
          var timestamp = captureTimestamp(sample, serverMode());
          if (timestamp.isEmpty()
              || timestamp.getAsDouble() <= resetTimestamp
              || !observation.getCameraName().equals(camera.getKey())
              || !observation.getServiceSession().equals(acknowledgement.getServiceSession())
              || !observation.getRuntimeGeneration().equals(acknowledgement.getRuntimeGeneration())
              || observation.getConnectionEpoch() != acknowledgement.getConnectionEpoch()
              || observation.getSyncEpoch() != acknowledgement.getSyncEpoch()) {
            continue;
          }
          result.add(new Sample(observation, timestamp.getAsDouble()));
        } catch (InvalidProtocolBufferException exception) {
          malformed++;
        }
      }
    }
    return new Inputs(health, result);
  }

  @Override
  public void reportDecision(Sample sample, VisionProcessor.Decision decision) {
    var observation = sample.observation();
    if (!cameras.containsKey(observation.getCameraName())) {
      return;
    }
    var values = new HashMap<String, Object>();
    values.put("state", decision.reason().name());
    values.put("fused", false);
    values.put("capture_epoch", observation.getCaptureEpoch());
    values.put("sequence", observation.getSequence());
    values.put("capture_fpga_s", sample.captureFpgaSeconds());
    values.put("service_session", observation.getServiceSession());
    values.put("runtime_generation", observation.getRuntimeGeneration());
    values.put("connection_epoch", observation.getConnectionEpoch());
    values.put("sync_epoch", observation.getSyncEpoch());
    values.put("tag_selection_generation", observation.getTagSelectionGeneration());
    values.put("frame_id", decision.measurement().map(VisionMeasurement::frameId).orElse(""));
    decisions.put(observation.getCameraName(), values);
  }

  @Override
  public void reset(double timestamp) {
    resetTimestamp = timestamp;
    decisions.clear();
    for (var camera : cameras.values()) {
      camera.readQueue();
    }
  }

  @Override
  public void setFusionEnabled(boolean enabled) {
    effectiveFusion = enabled;
  }

  @Override
  public void setTagSelection(TagSelection selection) {
    this.selection = selection;
    decisions.clear();
  }

  private Health health(double now) {
    String reason = "";
    if (!serverMode()) {
      reason = "Robot must be NT server";
    } else if (!acknowledgement.getApplied()) {
      reason = "Waiting for configuration acknowledgement";
    } else if (!acknowledgement.getTagSelectionSupported()) {
      reason = "Spot service does not support tag selection";
    } else if (now - lastHealthTimestamp > .5 || lastHealthTimestamp > now + .005) {
      reason = "Spot heartbeat stale";
    } else if (!lastHealth.getSyncState().equals("Synchronized")
        || !lastHealth.getServiceSession().equals(acknowledgement.getServiceSession())
        || lastHealth.getSyncEpoch() != acknowledgement.getSyncEpoch()
        || lastHealth.getConnectionEpoch() != acknowledgement.getConnectionEpoch()
        || !lastHealth.getRuntimeGeneration().equals(acknowledgement.getRuntimeGeneration())) {
      reason = "Waiting for synchronized current session";
    }
    return new Health(reason.isEmpty(), reason, acknowledgement, lastHealth);
  }

  private boolean serverMode() {
    return instance.getNetworkMode().contains(NetworkTableInstance.NetworkMode.kServer);
  }

  private RawSubscriber subscribe(String topic, String type, int capacity) {
    return instance
        .getRawTopic(topic)
        .subscribe(
            "proto:spot.vision.v2." + type,
            new byte[0],
            PubSubOption.sendAll(true),
            PubSubOption.keepDuplicates(true),
            PubSubOption.pollStorage(capacity),
            PubSubOption.periodic(.005));
  }

  private void update(double now, boolean robotEnabled) {
    if (!serverMode()) {
      return;
    }
    statePublisher.set(
        SpotProtos.RobotState.newBuilder()
            .setRobotSession(manifest.getRobotSession())
            .setEnabled(robotEnabled)
            .setTagSelectionGeneration(selection == null ? 0 : selection.generation())
            .addAllAllowedTagIds(selection == null ? ImmutableList.of() : selection.allowedTagIds())
            .setSequence(++stateSequence)
            .build()
            .toByteArray());
    if (now - lastPublish >= MANIFEST_PERIOD_S) {
      manifestPublisher.set(manifest.toByteArray());
      lastPublish = now;
    }
    for (var sample : ackSubscriber.readQueue()) {
      if (sample.value.length > 65536) {
        malformed++;
        continue;
      }
      try {
        var candidate = SpotProtos.Acknowledgement.parseFrom(sample.value);
        if (candidate.getApplied()
            && candidate.getSchemaVersion() == 2
            && candidate.getRobotSession().equals(manifest.getRobotSession())
            && candidate.getRobotId().equals(manifest.getProfile().getRobotId())
            && candidate.getManifestHash().equals(manifest.getManifestHash())
            && candidate.getFieldHash().equals(SpotProtocol.hash(manifest.getProfile().getField()))
            && !candidate.getServiceSession().isEmpty()
            && !candidate.getRuntimeGeneration().isEmpty()
            && candidate.getConnectionEpoch() > 0
            && candidate.getSyncEpoch() > 0
            && candidate.getCamerasCount() <= 32) {
          acknowledgement = candidate;
        } else {
          acknowledgement = SpotProtos.Acknowledgement.getDefaultInstance();
        }
      } catch (InvalidProtocolBufferException exception) {
        malformed++;
      }
    }
    for (var sample : healthSubscriber.readQueue()) {
      if (sample.value.length > 65536) {
        malformed++;
        continue;
      }
      try {
        var health = SpotProtos.Health.parseFrom(sample.value);
        var timestamp = captureTimestamp(sample, serverMode());
        if (health.getSchemaVersion() != 2
            || timestamp.isEmpty()
            || health.getSequence() == 0
            || (health.getServiceSession().equals(lastHealth.getServiceSession())
                && health.getSequence() <= lastHealth.getSequence())) {
          continue;
        }
        lastHealth = health;
        lastHealthTimestamp = timestamp.getAsDouble();
      } catch (InvalidProtocolBufferException exception) {
        malformed++;
      }
    }
    var currentGeneration =
        acknowledgement.getServiceSession()
            + "/"
            + acknowledgement.getRuntimeGeneration()
            + "/"
            + acknowledgement.getConnectionEpoch()
            + "/"
            + acknowledgement.getSyncEpoch();
    if (!generation.equals(currentGeneration)) {
      generation = currentGeneration;
      decisions.clear();
      // The old NT queue can contain frames from any earlier generation. Drain
      // below and validate each packet; clearing blindly can lose the first
      // current-generation frame without improving safety.
    }
  }
}
