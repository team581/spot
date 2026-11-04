// Move to shared folder after offseason
package frc.robot.vision;

import com.fasterxml.jackson.databind.ObjectMapper;
import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.networktables.PubSubOption;
import edu.wpi.first.networktables.RawSubscriber;
import edu.wpi.first.networktables.StringPublisher;
import edu.wpi.first.networktables.StringSubscriber;
import edu.wpi.first.networktables.StructPublisher;
import edu.wpi.first.networktables.TimestampedRaw;
import edu.wpi.first.util.struct.StructBuffer;
import frc.robot.vision.data.*;
import frc.robot.vision.results.VisionMeasurement;
import frc.robot.vision.structs.FrameResult;
import frc.robot.vision.structs.Heartbeat;
import frc.robot.vision.structs.RobotStatus;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.OptionalDouble;

/** NT4 robot server adapter; transport bytes and metadata stay atomic. */
public final class SpotVisionIO implements VisionIO {
  public static final String ROOT = "/Spot";
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
  private final Manifest manifest;
  private final String fieldHash;
  private final StringPublisher manifestPublisher;
  private final StringPublisher sessionPublisher;
  private final StructPublisher<RobotStatus> statePublisher;
  private final StringSubscriber ackSubscriber;
  private final RawSubscriber healthSubscriber;
  private final StructBuffer<FrameResult> frameBuffer = StructBuffer.create(FrameResult.struct);
  private final StructBuffer<Heartbeat> healthBuffer = StructBuffer.create(Heartbeat.struct);
  private final SpotMetadata metadata;
  private final long[] sessionToken;
  private final Map<String, long[]> frameContexts = new HashMap<>();
  private final StringPublisher decisionsPublisher;
  private final Map<String, Map<String, Object>> decisions = new HashMap<>();
  private double lastDecisionPublish = Double.NEGATIVE_INFINITY;
  private final Map<String, RawSubscriber> cameras = new HashMap<>();
  private Acknowledgement acknowledgement =
      new Acknowledgement("", "", "", "", 0L, 0L, "", "", java.util.List.of(), false, "", false);
  private frc.robot.vision.data.Health lastHealth =
      new frc.robot.vision.data.Health(
          "", 0L, 0.0, "", 0L, 0.0, 0L, 0L, 0L, "", "", "", java.util.List.of());
  private double lastHealthTimestamp = Double.NEGATIVE_INFINITY;
  private double lastPublish = Double.NEGATIVE_INFINITY;
  private double resetTimestamp = Double.NEGATIVE_INFINITY;
  private long stateSequence;

  private long malformed;

  private String generation = "";
  private TagSelection selection;
  private boolean effectiveFusion;
  private boolean closed;

  public SpotVisionIO(NetworkTableInstance instance, Profile profile, String session) {
    this.instance = instance;
    this.manifest = new Manifest(profile, session, SpotProtocol.hash(profile));
    fieldHash = SpotProtocol.hash(profile.field());
    metadata = new SpotMetadata(instance, ROOT);
    metadata.publish(profile);
    sessionToken = SpotProtocol.token(session);
    sessionPublisher = instance.getStringTopic(ROOT + "/robot/session").publish();
    sessionPublisher.set(session);
    manifestPublisher =
        instance
            .getStringTopic(ROOT + "/robot/manifest")
            .publish(
                PubSubOption.sendAll(true),
                PubSubOption.keepDuplicates(true),
                PubSubOption.periodic(.02));
    statePublisher =
        instance
            .getStructTopic(ROOT + "/robot/state", RobotStatus.struct)
            .publish(
                PubSubOption.sendAll(true),
                PubSubOption.keepDuplicates(true),
                PubSubOption.periodic(.02));
    ackSubscriber = instance.getStringTopic(ROOT + "/config/ack").subscribe("");
    healthSubscriber =
        instance
            .getRawTopic(ROOT + "/health")
            .subscribe(
                Heartbeat.struct.getTypeString(),
                new byte[0],
                PubSubOption.sendAll(true),
                PubSubOption.keepDuplicates(true),
                PubSubOption.pollStorage(16));
    decisionsPublisher =
        instance.getStringTopic(ROOT + "/robot/decisions").publish(PubSubOption.periodic(1.0));
    for (var camera : profile.cameras()) {
      cameras.put(
          camera.name(),
          instance
              .getRawTopic(ROOT + "/" + camera.name() + "/observations")
              .subscribe(
                  FrameResult.struct.getTypeString(),
                  new byte[0],
                  PubSubOption.sendAll(true),
                  PubSubOption.keepDuplicates(true),
                  PubSubOption.pollStorage(16),
                  PubSubOption.periodic(.005)));
    }
  }

  @Override
  public void close() {
    if (closed) return;
    closed = true;
    metadata.close();
    decisionsPublisher.close();
    manifestPublisher.close();
    sessionPublisher.close();
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

  public Manifest manifest() {
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
              && acknowledgement.runtimeGeneration().equals(values.get("runtime_generation"))
              && acknowledgement.serviceSession().equals(values.get("service_session"))
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
                  manifest.robotSession(),
                  "manifest_hash",
                  manifest.manifestHash(),
                  "fusion_enabled",
                  effectiveFusion,
                  "heading_enabled",
                  manifest.profile().headingEnabled(),
                  "revised_trust_enabled",
                  manifest.profile().revisedTrustEnabled(),
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
        if (!health.available()) {
          continue;
        }
        try {
          if (sample.value.length != FrameResult.struct.getSize())
            throw new IllegalArgumentException("Incorrect frame struct size");
          var frame = frameBuffer.read(sample.value);
          var timestamp = captureTimestamp(sample, serverMode());
          var context = frameContexts.get(camera.getKey());
          if (timestamp.isEmpty()
              || timestamp.getAsDouble() <= resetTimestamp
              || context == null
              || frame.contextHigh() != context[0]
              || frame.contextLow() != context[1]) {
            continue;
          }
          var applied =
              acknowledgement.cameras().stream()
                  .filter(c -> c.cameraName().equals(camera.getKey()))
                  .findFirst()
                  .orElseThrow();
          var observation =
              SpotFrames.observation(frame, acknowledgement, applied, manifest.profile());
          result.add(new Sample(observation, timestamp.getAsDouble(), frame));
        } catch (IllegalArgumentException exception) {
          malformed++;
        }
      }
    }
    return new Inputs(health, result);
  }

  @Override
  public void reportDecision(Sample sample, VisionProcessor.Decision decision) {
    var observation = sample.observation();
    if (!cameras.containsKey(observation.cameraName())) {
      return;
    }
    var values = new HashMap<String, Object>();
    values.put("state", decision.reason().name());
    values.put("fused", false);
    values.put("capture_epoch", observation.captureEpoch());
    values.put("sequence", observation.sequence());
    values.put("capture_fpga_s", sample.captureFpgaSeconds());
    values.put("service_session", observation.serviceSession());
    values.put("runtime_generation", observation.runtimeGeneration());
    values.put("connection_epoch", observation.connectionEpoch());
    values.put("sync_epoch", observation.syncEpoch());
    values.put("tag_selection_generation", observation.tagSelectionGeneration());
    values.put("frame_id", decision.measurement().map(VisionMeasurement::frameId).orElse(""));
    decisions.put(observation.cameraName(), values);
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
    } else if (!acknowledgement.applied()) {
      reason = "Waiting for configuration acknowledgement";
    } else if (!acknowledgement.tagSelectionSupported()) {
      reason = "Spot service does not support tag selection";
    } else if (now - lastHealthTimestamp > .5 || lastHealthTimestamp > now + .005) {
      reason = "Spot heartbeat stale";
    } else if (!lastHealth.syncState().equals("Synchronized")
        || !lastHealth.serviceSession().equals(acknowledgement.serviceSession())
        || lastHealth.syncEpoch() != acknowledgement.syncEpoch()
        || lastHealth.connectionEpoch() != acknowledgement.connectionEpoch()
        || !lastHealth.runtimeGeneration().equals(acknowledgement.runtimeGeneration())) {
      reason = "Waiting for synchronized current session";
    }
    return new Health(reason.isEmpty(), reason, acknowledgement, lastHealth);
  }

  private boolean serverMode() {
    return instance.getNetworkMode().contains(NetworkTableInstance.NetworkMode.kServer);
  }

  private void update(double now, boolean robotEnabled) {
    if (!serverMode()) {
      return;
    }
    statePublisher.set(
        new RobotStatus(
            sessionToken[0],
            sessionToken[1],
            robotEnabled,
            ++stateSequence,
            selection == null ? 0 : selection.generation(),
            selection == null
                ? 0
                : SpotProtocol.tagMask(selection.allowedTagIds(), manifest.profile().field())));
    if (now - lastPublish >= MANIFEST_PERIOD_S) {
      manifestPublisher.set(manifest.manifestHash());
      lastPublish = now;
    }
    metadata
        .acknowledgement(ackSubscriber.get())
        .ifPresent(candidate -> {
          if (candidate.applied()
              && candidate.robotSession().equals(manifest.robotSession())
              && candidate.robotId().equals(manifest.profile().robotId())
              && candidate.manifestHash().equals(manifest.manifestHash())
              && candidate.fieldHash().equals(fieldHash)
              && !candidate.serviceSession().isEmpty()
              && !candidate.runtimeGeneration().isEmpty()
              && candidate.connectionEpoch() > 0
              && candidate.syncEpoch() > 0
              && candidate.cameras().size() <= 32) {
            if (!candidate.equals(acknowledgement)) {
              acknowledgement = candidate;
              frameContexts.clear();
              for (var camera : candidate.cameras()) {
                frameContexts.put(
                    camera.cameraName(), SpotProtocol.frameContext(candidate, camera.cameraName()));
              }
            }
          } else {
            acknowledgement =
                new Acknowledgement(
                    "", "", "", "", 0L, 0L, "", "", java.util.List.of(), false, "", false);
            frameContexts.clear();
          }
        });
    for (var sample : healthSubscriber.readQueue()) {
      if (!acknowledgement.applied()) continue;
      try {
        if (sample.value.length != Heartbeat.struct.getSize())
          throw new IllegalArgumentException("Incorrect heartbeat struct size");
        var health = SpotFrames.health(healthBuffer.read(sample.value), acknowledgement);
        var timestamp = captureTimestamp(sample, serverMode());
        if (timestamp.isEmpty()
            || health.sequence() == 0
            || (health.serviceSession().equals(lastHealth.serviceSession())
                && health.sequence() <= lastHealth.sequence())) {
          continue;
        }
        lastHealth = health;
        lastHealthTimestamp = timestamp.getAsDouble();
      } catch (IllegalArgumentException exception) {
        malformed++;
      }
    }
    var currentGeneration =
        acknowledgement.serviceSession()
            + "/"
            + acknowledgement.runtimeGeneration()
            + "/"
            + acknowledgement.connectionEpoch()
            + "/"
            + acknowledgement.syncEpoch();
    if (!generation.equals(currentGeneration)) {
      generation = currentGeneration;
      decisions.clear();
      // The old NT queue can contain frames from any earlier generation. Drain
      // below and validate each packet; clearing blindly can lose the first
      // current-generation frame without improving safety.
    }
  }
}
