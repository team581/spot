// Move to shared folder after offseason
package frc.robot.vision;

import com.google.common.collect.ImmutableSet;
import com.google.common.collect.Sets;
import edu.wpi.first.math.MathUtil;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.math.geometry.Transform3d;
import frc.robot.vision.generated.SpotProtos;
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
    SCHEMA,
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
              .filter(
                  other ->
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

  private static boolean validPose(SpotProtos.Pose pose) {
    double[] values = {
      pose.getXM(),
      pose.getYM(),
      pose.getZM(),
      pose.getQw(),
      pose.getQx(),
      pose.getQy(),
      pose.getQz()
    };
    for (double value : values) {
      if (!Double.isFinite(value)) {
        return false;
      }
    }
    double norm =
        pose.getQw() * pose.getQw()
            + pose.getQx() * pose.getQx()
            + pose.getQy() * pose.getQy()
            + pose.getQz() * pose.getQz();
    return MathUtil.isNear(norm, 1.0, 1e-6);
  }

  private final SpotProtos.Profile profile;
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
      SpotProtos.Profile profile,
      List<SpotCameraProfiles.Camera> cameras,
      History history,
      Policy policy) {
    this.profile = profile;
    this.cameras = new HashMap<>();
    for (var camera : cameras) {
      this.cameras.put(camera.name(), camera);
    }
    this.history = history;
    this.policy = policy;
    knownTags =
        Set.copyOf(
            profile.getField().getTagsList().stream().map(SpotProtos.FieldTag::getId).toList());
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
      VisionIO.Sample sample, SpotProtos.Acknowledgement ack, double now, boolean initialization) {
    var observation = sample.observation();
    double timestamp = sample.captureFpgaSeconds();
    if (observation.getSchemaVersion() != 2 || observation.getSerializedSize() > 65536) {
      return Decision.reject(Reason.SCHEMA);
    }
    if (!ack.getApplied()
        || ack.getSchemaVersion() != 2
        || !ack.getManifestHash().equals(SpotProtocol.hash(profile))
        || !observation.getRobotId().equals(profile.getRobotId())
        || !observation.getRobotSession().equals(ack.getRobotSession())
        || !observation.getServiceSession().equals(ack.getServiceSession())
        || !observation.getManifestHash().equals(ack.getManifestHash())
        || !observation.getFieldHash().equals(ack.getFieldHash())
        || !observation.getFieldHash().equals(SpotProtocol.hash(profile.getField()))
        || !observation.getRuntimeGeneration().equals(ack.getRuntimeGeneration())
        || observation.getConnectionEpoch() != ack.getConnectionEpoch()
        || observation.getSyncEpoch() != ack.getSyncEpoch()) {
      return Decision.reject(Reason.CONFIGURATION);
    }
    var cameraGeneration =
        ack.getCamerasList().stream()
            .filter(camera -> camera.getCameraName().equals(observation.getCameraName()))
            .findFirst();
    if (cameraGeneration.isEmpty()) {
      return Decision.reject(Reason.CONFIGURATION);
    }
    var applied = cameraGeneration.orElseThrow();
    var definition =
        profile.getCamerasList().stream()
            .filter(camera -> camera.getName().equals(observation.getCameraName()))
            .findFirst();
    if (definition.isEmpty()
        || !definition.orElseThrow().getEnabled()
        || !observation.getBindingId().equals(applied.getBindingId())
        || observation.getBindingGeneration() != applied.getBindingGeneration()
        || !observation.getCalibrationHash().equals(applied.getCalibrationHash())
        || !observation.getModeId().equals(applied.getModeId())
        || !observation.getOpticalSignature().equals(applied.getOpticalSignature())
        || definition.orElseThrow().getAllowedModesList().stream()
            .noneMatch(
                mode ->
                    mode.getId().equals(observation.getModeId())
                        && mode.getOpticalSignature().equals(observation.getOpticalSignature()))) {
      return Decision.reject(Reason.CONFIGURATION);
    }
    if (!Double.isFinite(now) || !Double.isFinite(timestamp) || timestamp <= 0) {
      return Decision.reject(Reason.TIMESTAMP);
    }
    if (timestamp <= resetTimestamp) {
      return Decision.reject(Reason.RESET);
    }
    if (timestamp > now + profile.getFutureToleranceS()) {
      return Decision.reject(Reason.FUTURE);
    }
    if (now - timestamp > profile.getMaxAgeS()) {
      return Decision.reject(Reason.STALE);
    }
    if (observation.getCaptureEpoch().isEmpty()
        || observation.getSequence() <= 0
        || observation.getTagsCount() > 64
        || observation.getCandidatesCount() > 2) {
      return Decision.reject(Reason.MALFORMED);
    }
    var timing = observation.getTiming();
    for (double value :
        new double[] {
          timing.getCaptureToDetectMs(),
          timing.getDetectMs(),
          timing.getSolveMs(),
          timing.getTotalMs()
        }) {
      if (!Double.isFinite(value) || value < 0) {
        return Decision.reject(Reason.MALFORMED);
      }
    }
    Set<Integer> observedTags = new HashSet<>();
    for (var tag : observation.getTagsList()) {
      if (tag.getCornersXyPxCount() != 8
          || tag.getCornersXyPxList().stream().anyMatch(value -> !Double.isFinite(value))
          || !observedTags.add(tag.getId())) {
        return Decision.reject(Reason.MALFORMED);
      }
    }
    String epoch = observation.getServiceSession() + "/" + observation.getCaptureEpoch();
    String key = observation.getCameraName() + "/" + epoch;
    if (retiredEpochs.contains(key)) {
      return Decision.reject(Reason.OLD_EPOCH);
    }
    String previousEpoch = currentEpoch.put(observation.getCameraName(), epoch);
    if (previousEpoch != null && !previousEpoch.equals(epoch)) {
      retiredEpochs.add(observation.getCameraName() + "/" + previousEpoch);
      if (retiredEpochs.size() > 128) {
        // Bounded memory: a wildly flapping camera remains rejected until a new
        // service/runtime handshake, rather than forgetting an old epoch.
        currentEpoch.put(observation.getCameraName(), previousEpoch);
        return Decision.reject(Reason.OLD_EPOCH);
      }
    }
    long sequence = observation.getSequence();
    if (sequence <= lastSequence.getOrDefault(key, 0L)) {
      return Decision.reject(Reason.DUPLICATE);
    }
    lastSequence.put(key, sequence);
    if (!applied.getCalibrationValid()
        || !observation.getCalibrationValid()
        || applied.getCalibrationHash().isEmpty()) {
      return Decision.reject(Reason.CALIBRATION);
    }
    var camera = cameras.get(observation.getCameraName());
    var policy =
        camera == null || camera.qualityPolicy() == null ? this.policy : camera.qualityPolicy();
    double timeUncertainty = observation.getTimestampUncertaintyS();
    if (!Double.isFinite(timeUncertainty)
        || timeUncertainty <= 0
        || timeUncertainty > policy.maxTimestampUncertaintyS()
        || !ImmutableSet.of(
                "read-completion-local-nt",
                "driver-exposure-start-local-nt",
                "driver-exposure-end-local-nt")
            .contains(observation.getTimestampSource())) {
      return Decision.reject(Reason.TIMESTAMP);
    }
    if (observation.getCandidatesCount() == 0) {
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
    for (var candidate : observation.getCandidatesList()) {
      if (!validPose(candidate.getFieldToCamera())
          || candidate.getTagIdsCount() == 0
          || candidate.getTagIdsCount() > 64
          || new HashSet<>(candidate.getTagIdsList()).size() != candidate.getTagIdsCount()
          || !Double.isFinite(candidate.getAverageTagDistanceM())
          || candidate.getAverageTagDistanceM() <= 0
          || !Double.isFinite(candidate.getReprojectionErrorPx())
          || candidate.getReprojectionErrorPx() < 0
          || !Double.isFinite(candidate.getImageAreaFraction())
          || candidate.getImageAreaFraction() <= 0
          || candidate.getImageAreaFraction() > 1
          || !Double.isFinite(candidate.getImageSpreadFraction())
          || candidate.getImageSpreadFraction() < 0
          || candidate.getImageSpreadFraction() > 1
          || !Sets.immutableEnumSet(
                  SpotProtos.PoseCandidate.Method.MULTI_TAG_SQPNP,
                  SpotProtos.PoseCandidate.Method.SINGLE_TAG_IPPE_SQUARE)
              .contains(candidate.getMethod())) {
        return Decision.reject(Reason.MALFORMED);
      }
      if (!knownTags.containsAll(candidate.getTagIdsList())) {
        return Decision.reject(Reason.UNKNOWN_TAG);
      }
      if (!observedTags.containsAll(candidate.getTagIdsList())) {
        return Decision.reject(Reason.MALFORMED);
      }
      if (candidate.getMethod() != observation.getCandidates(0).getMethod()
          || (candidate.getMethod() == SpotProtos.PoseCandidate.Method.SINGLE_TAG_IPPE_SQUARE
              && (candidate.getTagIdsCount() != 1
                  || !candidate
                      .getTagIdsList()
                      .equals(observation.getCandidates(0).getTagIdsList())))) {
        return Decision.reject(Reason.MALFORMED);
      }
      var fieldCamera = SpotProtocol.pose(candidate.getFieldToCamera());
      for (int tagId : candidate.getTagIdsList()) {
        var tag =
            profile.getField().getTagsList().stream()
                .filter(value -> value.getId() == tagId)
                .findFirst()
                .orElseThrow();
        var cameraToTag = new Transform3d(fieldCamera, SpotProtocol.pose(tag.getFieldToTag()));
        if (cameraToTag.getX() <= .05) {
          return Decision.reject(Reason.MALFORMED);
        }
      }
      if (candidate.getReprojectionErrorPx() > policy.maxResidualPx()) {
        return Decision.reject(Reason.RESIDUAL);
      }
      alternatives.add(
          SpotProtocol.pose(candidate.getFieldToCamera())
              .transformBy(mount.orElseThrow().inverse()));
    }
    int selected = 0;
    if (observation.getCandidates(0).getMethod()
        == SpotProtos.PoseCandidate.Method.SINGLE_TAG_IPPE_SQUARE) {
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
    } else if (alternatives.size() != 1 || observation.getCandidates(0).getTagIdsCount() < 2) {
      return Decision.reject(Reason.MALFORMED);
    }
    var robot = alternatives.get(selected);
    if (robot.getX() < -.25
        || robot.getX() > profile.getField().getLengthM() + .25
        || robot.getY() < -.25
        || robot.getY() > profile.getField().getWidthM() + .25) {
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
    var candidate = observation.getCandidates(selected);
    double range = candidate.getAverageTagDistanceM();
    double conditioning = MathUtil.clamp(Math.sqrt(.02 / candidate.getImageAreaFraction()), 1., 4.);
    // Count benefit capped at sqrt(3). Overlapping simultaneous cameras are
    // additionally inflated by correlation policy at source collection.
    double sigma =
        Math.max(
                policy.translationFloorM(),
                policy.rangeSquaredCoefficient()
                    * range
                    * range
                    / Math.sqrt(Math.min(3, candidate.getTagIdsCount())))
            * conditioning
            * (1 + candidate.getReprojectionErrorPx() / policy.maxResidualPx());
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
            observation.getCameraName(),
            key
                + "/"
                + observation.getRuntimeGeneration()
                + "/"
                + observation.getConnectionEpoch()
                + "/"
                + observation.getSyncEpoch()
                + "/"
                + observation.getTagSelectionGeneration()
                + "/"
                + sequence,
            robot.toPose2d(),
            timestamp,
            sigma,
            sigma,
            profile.getHeadingEnabled() ? Math.max(.2, sigma / range) : 1e6,
            candidate.getTagIdsList(),
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
