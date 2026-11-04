// Move to shared folder after offseason
package frc.robot.vision;

import com.google.common.collect.ImmutableSet;
import com.google.common.collect.Sets;
import edu.wpi.first.math.MathUtil;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.math.geometry.Transform3d;
import frc.robot.vision.data.*;
import frc.robot.vision.results.VisionMeasurement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Robot-owned geometry, candidate selection and conservative quality model. */
public final class VisionProcessor {
  public record CaptureState(
      Pose2d pose,
      double speedMps,
      double angularRateRadPerS,
      double rollRad,
      double pitchRad,
      double zM) {}

  public record Decision(Reason reason, Optional<VisionMeasurement> measurement) {
    public static Decision reject(Reason reason) {
      return new Decision(reason, Optional.empty());
    }
  }

  public interface History {
    Optional<CaptureState> at(double fpgaSeconds);
  }

  public record Policy(
      double translationFloorM,
      double rangeSquaredCoefficient,
      double maxResidualPx,
      double candidateHeadingMarginRad,
      double maxHeadingDifferenceRad,
      double innovationSigma,
      double maxZErrorM,
      double maxTiltErrorRad,
      double maxTimestampUncertaintyS) {
    public static Policy conservative() {
      // Engineering defaults, requiring held-out robot trials. Heading remains
      // suppressed with a large finite deviation supported by CTRE's interface.
      return new Policy(
          .04, .015, 2.0, Math.toRadians(15), Math.toRadians(35), 5.0, .5, Math.toRadians(30), .02);
    }
  }

  public enum Reason {
    ACCEPTED,
    NO_TAGS,
    CONFIGURATION,
    CALIBRATION,
    TIMESTAMP,
    STALE,
    FUTURE,
    DUPLICATE,
    OLD_EPOCH,
    RESET,
    MALFORMED,
    UNKNOWN_TAG,
    HISTORY,
    MOUNT_HISTORY,
    FIELD_BOUNDS,
    ROBOT_TILT,
    AMBIGUOUS,
    RESIDUAL,
    INNOVATION,
    TAG_POLICY
  }

  /** Conservative approximation: do not treat same-tag simultaneous views as independent. */
  public static List<VisionMeasurement> accountForCorrelation(
      List<VisionMeasurement> observations) {
    return accountForCorrelation(observations, 1);
  }

  public static List<VisionMeasurement> accountForCorrelation(
      List<VisionMeasurement> observations, int maximumSources) {
    var result = new ArrayList<VisionMeasurement>();
    for (var observation : observations) {
      long correlated =
          observations.stream()
              .filter(other ->
                  MathUtil.isNear(other.timestamp(), observation.timestamp(), .02)
                      && other.tagIds().stream().anyMatch(observation.tagIds()::contains))
              .map(VisionMeasurement::source)
              .distinct()
              .count();
      double factor = Math.sqrt((double) Math.max(maximumSources, correlated));
      result.add(
          new VisionMeasurement(
              observation.source(),
              observation.frameId(),
              observation.pose(),
              observation.timestamp(),
              observation.stdX() * factor,
              observation.stdY() * factor,
              observation.stdHeading() * factor,
              observation.tagIds(),
              observation.innovationM(),
              observation.normalizedInnovation() / factor));
    }
    return List.copyOf(result);
  }

  private static double headingError(Pose3d candidate, Pose2d history) {
    return Math.abs(candidate.toPose2d().getRotation().minus(history.getRotation()).getRadians());
  }

  private static boolean validPose(Pose pose) {
    double[] values = {pose.xM(), pose.yM(), pose.zM(), pose.qw(), pose.qx(), pose.qy(), pose.qz()};
    for (double value : values) {
      if (!Double.isFinite(value)) {
        return false;
      }
    }
    double norm =
        pose.qw() * pose.qw()
            + pose.qx() * pose.qx()
            + pose.qy() * pose.qy()
            + pose.qz() * pose.qz();
    return MathUtil.isNear(norm, 1.0, 1e-6);
  }

  private final Profile profile;
  private final String profileHash;
  private final String fieldHash;
  private final Map<String, SpotCameraProfiles.Camera> cameras;
  private final History history;
  private final Policy policy;
  private final Set<Integer> knownTags;
  private final Map<String, Long> lastSequence = new HashMap<>();

  private final Map<String, String> currentEpoch = new HashMap<>();

  private final Set<String> retiredEpochs = new HashSet<>();

  private double resetTimestamp = Double.NEGATIVE_INFINITY;

  private String generation = "";

  public VisionProcessor(
      Profile profile, List<SpotCameraProfiles.Camera> cameras, History history, Policy policy) {
    this.profile = profile;
    this.profileHash = SpotProtocol.hash(profile);
    this.fieldHash = SpotProtocol.hash(profile.field());
    this.cameras = new HashMap<>();
    for (var camera : cameras) {
      this.cameras.put(camera.name(), camera);
    }
    this.history = history;
    this.policy = policy;
    knownTags = Set.copyOf(profile.field().tags().stream().map(FieldTag::id).toList());
  }

  public void newGeneration(String identity) {
    if (!identity.equals(generation)) {
      generation = identity;
      lastSequence.clear();
      currentEpoch.clear();
      retiredEpochs.clear();
    }
  }

  public Decision process(
      VisionIO.Sample sample, Acknowledgement ack, double now, boolean initialization) {
    var observation = sample.observation();
    double timestamp = sample.captureFpgaSeconds();
    if (!ack.applied()
        || !ack.manifestHash().equals(profileHash)
        || !observation.robotId().equals(profile.robotId())
        || !observation.robotSession().equals(ack.robotSession())
        || !observation.serviceSession().equals(ack.serviceSession())
        || !observation.manifestHash().equals(ack.manifestHash())
        || !observation.fieldHash().equals(ack.fieldHash())
        || !observation.fieldHash().equals(fieldHash)
        || !observation.runtimeGeneration().equals(ack.runtimeGeneration())
        || observation.connectionEpoch() != ack.connectionEpoch()
        || observation.syncEpoch() != ack.syncEpoch()) {
      return Decision.reject(Reason.CONFIGURATION);
    }
    var cameraGeneration =
        ack.cameras().stream()
            .filter(camera -> camera.cameraName().equals(observation.cameraName()))
            .findFirst();
    if (cameraGeneration.isEmpty()) {
      return Decision.reject(Reason.CONFIGURATION);
    }
    var applied = cameraGeneration.orElseThrow();
    var definition =
        profile.cameras().stream()
            .filter(camera -> camera.name().equals(observation.cameraName()))
            .findFirst();
    if (definition.isEmpty()
        || !definition.orElseThrow().enabled()
        || !observation.bindingId().equals(applied.bindingId())
        || observation.bindingGeneration() != applied.bindingGeneration()
        || !observation.calibrationHash().equals(applied.calibrationHash())
        || !observation.modeId().equals(applied.modeId())
        || !observation.opticalSignature().equals(applied.opticalSignature())
        || definition.orElseThrow().allowedModes().stream()
            .noneMatch(mode ->
                mode.id().equals(observation.modeId())
                    && mode.opticalSignature().equals(observation.opticalSignature()))) {
      return Decision.reject(Reason.CONFIGURATION);
    }
    if (!Double.isFinite(now) || !Double.isFinite(timestamp) || timestamp <= 0) {
      return Decision.reject(Reason.TIMESTAMP);
    }
    if (timestamp <= resetTimestamp) {
      return Decision.reject(Reason.RESET);
    }
    if (timestamp > now + profile.futureToleranceS()) {
      return Decision.reject(Reason.FUTURE);
    }
    if (now - timestamp > profile.maxAgeS()) {
      return Decision.reject(Reason.STALE);
    }
    if (observation.captureEpoch().isEmpty()
        || observation.sequence() <= 0
        || observation.tags().size() > 64
        || observation.candidates().size() > 2) {
      return Decision.reject(Reason.MALFORMED);
    }
    var timing = observation.timing();
    for (double value :
        new double[] {
          timing.captureToDetectMs(), timing.detectMs(), timing.solveMs(), timing.totalMs()
        }) {
      if (!Double.isFinite(value) || value < 0) {
        return Decision.reject(Reason.MALFORMED);
      }
    }
    Set<Integer> observedTags = new HashSet<>();
    for (var tag : observation.tags()) {
      if (!observedTags.add(tag.id())) {
        return Decision.reject(Reason.MALFORMED);
      }
    }
    String epoch = observation.serviceSession() + "/" + observation.captureEpoch();
    String key = observation.cameraName() + "/" + epoch;
    if (retiredEpochs.contains(key)) {
      return Decision.reject(Reason.OLD_EPOCH);
    }
    String previousEpoch = currentEpoch.put(observation.cameraName(), epoch);
    if (previousEpoch != null && !previousEpoch.equals(epoch)) {
      retiredEpochs.add(observation.cameraName() + "/" + previousEpoch);
      if (retiredEpochs.size() > 128) {
        // Bounded memory: a wildly flapping camera remains rejected until a new
        // service/runtime handshake, rather than forgetting an old epoch.
        currentEpoch.put(observation.cameraName(), previousEpoch);
        return Decision.reject(Reason.OLD_EPOCH);
      }
    }
    long sequence = observation.sequence();
    if (sequence <= lastSequence.getOrDefault(key, 0L)) {
      return Decision.reject(Reason.DUPLICATE);
    }
    lastSequence.put(key, sequence);
    if (!applied.calibrationValid()
        || !observation.calibrationValid()
        || applied.calibrationHash().isEmpty()) {
      return Decision.reject(Reason.CALIBRATION);
    }
    var camera = cameras.get(observation.cameraName());
    var policy =
        camera == null || camera.qualityPolicy() == null ? this.policy : camera.qualityPolicy();
    double timeUncertainty = observation.timestampUncertaintyS();
    if (!Double.isFinite(timeUncertainty)
        || timeUncertainty <= 0
        || timeUncertainty > policy.maxTimestampUncertaintyS()
        || !ImmutableSet.of(
                "read-completion-local-nt",
                "driver-exposure-start-local-nt",
                "driver-exposure-end-local-nt")
            .contains(observation.timestampSource())) {
      return Decision.reject(Reason.TIMESTAMP);
    }
    if (observation.candidates().size() == 0) {
      return Decision.reject(Reason.NO_TAGS);
    }
    var captured = history.at(timestamp);
    if (captured.isEmpty()) {
      return Decision.reject(Reason.HISTORY);
    }
    if (camera == null) {
      return Decision.reject(Reason.MOUNT_HISTORY);
    }
    Optional<Transform3d> mount = Optional.ofNullable(camera.mount());
    if (mount.isEmpty()) {
      return Decision.reject(Reason.MOUNT_HISTORY);
    }
    var alternatives = new ArrayList<Pose3d>();
    for (var candidate : observation.candidates()) {
      if (!validPose(candidate.fieldToCamera())
          || candidate.tagIds().size() == 0
          || candidate.tagIds().size() > 64
          || new HashSet<>(candidate.tagIds()).size() != candidate.tagIds().size()
          || !Double.isFinite(candidate.averageTagDistanceM())
          || candidate.averageTagDistanceM() <= 0
          || !Double.isFinite(candidate.reprojectionErrorPx())
          || candidate.reprojectionErrorPx() < 0
          || !Double.isFinite(candidate.imageAreaFraction())
          || candidate.imageAreaFraction() <= 0
          || candidate.imageAreaFraction() > 1
          || !Double.isFinite(candidate.imageSpreadFraction())
          || candidate.imageSpreadFraction() < 0
          || candidate.imageSpreadFraction() > 1
          || !Sets.immutableEnumSet(PoseMethod.MULTI_TAG_SQPNP, PoseMethod.SINGLE_TAG_IPPE_SQUARE)
              .contains(candidate.method())) {
        return Decision.reject(Reason.MALFORMED);
      }
      if (!knownTags.containsAll(candidate.tagIds())) {
        return Decision.reject(Reason.UNKNOWN_TAG);
      }
      if (!observedTags.containsAll(candidate.tagIds())) {
        return Decision.reject(Reason.MALFORMED);
      }
      if (candidate.method() != observation.candidates().get(0).method()
          || (candidate.method() == PoseMethod.SINGLE_TAG_IPPE_SQUARE
              && (candidate.tagIds().size() != 1
                  || !candidate.tagIds().equals(observation.candidates().get(0).tagIds())))) {
        return Decision.reject(Reason.MALFORMED);
      }
      var fieldCamera = SpotProtocol.pose(candidate.fieldToCamera());
      for (int tagId : candidate.tagIds()) {
        var tag =
            profile.field().tags().stream()
                .filter(value -> value.id() == tagId)
                .findFirst()
                .orElseThrow();
        var cameraToTag = new Transform3d(fieldCamera, SpotProtocol.pose(tag.fieldToTag()));
        if (cameraToTag.getX() <= .05) {
          return Decision.reject(Reason.MALFORMED);
        }
      }
      if (candidate.reprojectionErrorPx() > policy.maxResidualPx()) {
        return Decision.reject(Reason.RESIDUAL);
      }
      alternatives.add(
          SpotProtocol.pose(candidate.fieldToCamera()).transformBy(mount.orElseThrow().inverse()));
    }
    int selected = 0;
    if (observation.candidates().get(0).method() == PoseMethod.SINGLE_TAG_IPPE_SQUARE) {
      if (alternatives.size() != 2) {
        return Decision.reject(Reason.AMBIGUOUS);
      }
      double a = headingError(alternatives.get(0), captured.orElseThrow().pose());
      double b = headingError(alternatives.get(1), captured.orElseThrow().pose());
      if (MathUtil.isNear(a, b, policy.candidateHeadingMarginRad())
          || Math.min(a, b) > policy.maxHeadingDifferenceRad()) {
        return Decision.reject(Reason.AMBIGUOUS);
      }
      selected = a <= b ? 0 : 1;
    } else if (alternatives.size() != 1 || observation.candidates().get(0).tagIds().size() < 2) {
      return Decision.reject(Reason.MALFORMED);
    }
    var robot = alternatives.get(selected);
    if (robot.getX() < -.25
        || robot.getX() > profile.field().lengthM() + .25
        || robot.getY() < -.25
        || robot.getY() > profile.field().widthM() + .25) {
      return Decision.reject(Reason.FIELD_BOUNDS);
    }
    var state = captured.orElseThrow();
    for (double value :
        new double[] {
          state.speedMps(),
          state.angularRateRadPerS(),
          state.rollRad(),
          state.pitchRad(),
          state.zM()
        }) {
      if (!Double.isFinite(value)) {
        return Decision.reject(Reason.HISTORY);
      }
    }
    if (!MathUtil.isNear(robot.getZ(), state.zM(), policy.maxZErrorM())
        || !MathUtil.isNear(robot.getRotation().getX(), state.rollRad(), policy.maxTiltErrorRad())
        || !MathUtil.isNear(
            robot.getRotation().getY(), state.pitchRad(), policy.maxTiltErrorRad())) {
      return Decision.reject(Reason.ROBOT_TILT);
    }
    var candidate = observation.candidates().get(selected);
    double range = candidate.averageTagDistanceM();
    double conditioning = MathUtil.clamp(Math.sqrt(.02 / candidate.imageAreaFraction()), 1., 4.);
    // Count benefit capped at sqrt(3). Overlapping simultaneous cameras are
    // additionally inflated by correlation policy at source collection.
    double sigma =
        Math.max(
                policy.translationFloorM(),
                policy.rangeSquaredCoefficient()
                    * range
                    * range
                    / Math.sqrt(Math.min(3, candidate.tagIds().size())))
            * conditioning
            * (1 + candidate.reprojectionErrorPx() / policy.maxResidualPx());
    sigma =
        Math.hypot(
            sigma,
            timeUncertainty
                * (Math.abs(state.speedMps()) + Math.abs(state.angularRateRadPerS()) * range));
    double innovation =
        robot.toPose2d().getTranslation().getDistance(state.pose().getTranslation());
    double normalized = innovation / sigma;
    if (!Double.isFinite(normalized)
        || (!initialization && normalized > policy.innovationSigma())) {
      return Decision.reject(Reason.INNOVATION);
    }
    var measurement =
        new VisionMeasurement(
            observation.cameraName(),
            key
                + "/"
                + observation.runtimeGeneration()
                + "/"
                + observation.connectionEpoch()
                + "/"
                + observation.syncEpoch()
                + "/"
                + observation.tagSelectionGeneration()
                + "/"
                + sequence,
            robot.toPose2d(),
            timestamp,
            sigma,
            sigma,
            profile.headingEnabled() ? Math.max(.2, sigma / range) : 1e6,
            candidate.tagIds(),
            innovation,
            normalized);
    return new Decision(Reason.ACCEPTED, Optional.of(measurement));
  }

  public void reset(double timestamp) {
    resetTimestamp = timestamp;
    lastSequence.clear();
    currentEpoch.clear();
    retiredEpochs.clear();
  }
}
