package frc.robot.vision;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableMap;
import com.google.common.collect.ImmutableSet;
import com.google.common.collect.Sets;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.wpilibj.DriverStation.Alliance;
import frc.robot.logging.BenchLog;
import frc.robot.vision.data.*;
import frc.robot.vision.results.VisionMeasurement;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.BooleanSupplier;
import java.util.function.DoubleSupplier;
import java.util.function.Supplier;

/** Sole scheduled vision owner: collection, selection, ordering and cached observations. */
public final class Vision implements AutoCloseable {
  public record CameraStatus(
      double lastObservation,
      double lastAccepted,
      double lastFused,
      long accepted,
      long rejected,
      boolean usable,
      String reason) {}

  public interface CaptureSource {
    VisionProcessor.CaptureState current(double fpgaSeconds);

    Optional<Pose2d> poseAt(double fpgaSeconds);
  }

  public record Status(
      boolean available,
      String reason,
      int configured,
      int usable,
      int required,
      boolean allRequiredHealthy,
      long selectionGeneration,
      boolean selectionPending,
      int queueDepth,
      long queueDrops,
      String generation,
      Map<String, CameraStatus> cameras) {
    public Status {
      cameras = Map.copyOf(cameras);
    }
  }

  private static final Set<Integer> RED_HUB = Set.of(2, 3, 4, 5, 8, 9, 10, 11);
  private static final Set<Integer> BLUE_HUB = Set.of(18, 19, 20, 21, 24, 25, 26, 27);
  private VisionState state = VisionState.TAGS;

  private final VisionIO io;

  private final Profile profile;

  private final CaptureSource capture;
  private final DoubleSupplier clock;
  private final BooleanSupplier enabled;
  private final BooleanSupplier operatorVision;
  private final Supplier<Optional<Alliance>> alliance;
  private final CaptureHistory history;
  private final VisionProcessor processor;
  private final MeasurementQueue queue;
  private final Map<String, CameraStatus> cameras = new HashMap<>();
  private final Set<String> faults = new HashSet<>();
  private List<VisionMeasurement> prepared = ImmutableList.of();
  private final Map<String, VisionMeasurement> offered = new HashMap<>();
  private VisionIO.TagSelection selection;
  private Optional<Alliance> currentAlliance = Optional.empty();
  private String generation = "";
  private double now;
  private double lastHub = Double.NEGATIVE_INFINITY;
  private double lastTag = Double.NEGATIVE_INFINITY;
  private double resetTime = Double.NEGATIVE_INFINITY;
  private long appliedSelection;
  private boolean hasSeenTag;
  private boolean closed;
  private Status status =
      new Status(false, "No camera inputs", 0, 0, 0, false, 1, true, 0, 0, "", ImmutableMap.of());

  public Vision(
      VisionIO io,
      Profile profile,
      List<SpotCameraProfiles.Camera> mounts,
      CaptureSource capture,
      DoubleSupplier clock,
      BooleanSupplier enabled,
      BooleanSupplier operatorVision,
      Supplier<Optional<Alliance>> alliance) {
    this.io = io;
    this.profile = profile;
    this.capture = capture;
    this.clock = clock;
    this.enabled = enabled;
    this.operatorVision = operatorVision;
    this.alliance = alliance;
    history = new CaptureHistory(capture::poseAt);
    processor =
        new VisionProcessor(profile, mounts, history, VisionProcessor.Policy.conservative());
    queue = new MeasurementQueue(profile.reorderWindowS(), 128);
    selection = new VisionIO.TagSelection(1, broadTags());
    io.setTagSelection(selection);
  }

  public void close() {
    if (closed) return;
    closed = true;
    prepared = ImmutableList.of();
    offered.clear();
    queue.clearPending();
    for (var fault : faults) BenchLog.clearFault(fault);
    faults.clear();
    io.close();
  }

  public void collectInputs() {
    if (closed) return;
    now = clock.getAsDouble();
    prepared = ImmutableList.of();
    offered.clear();
    var observedAlliance = alliance.get();
    if (!observedAlliance.equals(currentAlliance)) {
      currentAlliance = observedAlliance;
      lastHub = Double.NEGATIVE_INFINITY;
      select(broadTags());
      if (getState() == VisionState.HUB_TAGS) setStateFromRequest(VisionState.WAITING_FOR_HUB_TAGS);
    }
    var inputs = io.readInputs(now, enabled.getAsBoolean());
    // Input collection can take long enough for newer exposures to arrive.
    // Validate age against the clock after collection, not its earlier start.
    now = clock.getAsDouble();
    history.add(now, capture.current(now));
    var health = inputs.health();
    var ack = health.acknowledgement();
    String epoch =
        ack.serviceSession()
            + "/"
            + ack.runtimeGeneration()
            + "/"
            + ack.connectionEpoch()
            + "/"
            + ack.syncEpoch();
    if (!epoch.equals(generation)) {
      generation = epoch;
      queue.clearPending();
      processor.newGeneration(epoch);
      retireObservations();
    }
    boolean available = health.available() && ack.tagSelectionSupported();
    boolean fusion = available && profile.fusionEnabled() && operatorVision.getAsBoolean();
    io.setFusionEnabled(fusion);
    if (!fusion) queue.clearPending();
    boolean pending = true;
    for (var sample : inputs.samples()) {
      if (profile.cameras().stream()
          .noneMatch(c -> c.name().equals(sample.observation().cameraName()))) continue;
      var observation = sample.observation();
      boolean matchingPolicy =
          observation.tagSelectionGeneration() == selection.generation()
              && observation.candidates().stream()
                  .allMatch(candidate -> selection.allowedTagIds().containsAll(candidate.tagIds()));
      var decision =
          !available
              ? VisionProcessor.Decision.reject(VisionProcessor.Reason.CONFIGURATION)
              : !matchingPolicy
                  ? VisionProcessor.Decision.reject(VisionProcessor.Reason.TAG_POLICY)
                  : processor.process(sample, ack, now, false);
      io.reportDecision(sample, decision);
      boolean accepted = decision.reason() == VisionProcessor.Reason.ACCEPTED;
      boolean operational =
          accepted
              || Set.of(
                      VisionProcessor.Reason.NO_TAGS,
                      VisionProcessor.Reason.HISTORY,
                      VisionProcessor.Reason.MOUNT_HISTORY,
                      VisionProcessor.Reason.FIELD_BOUNDS,
                      VisionProcessor.Reason.ROBOT_TILT,
                      VisionProcessor.Reason.AMBIGUOUS,
                      VisionProcessor.Reason.RESIDUAL,
                      VisionProcessor.Reason.INNOVATION)
                  .contains(decision.reason());
      if (operational) {
        pending = false;
        appliedSelection = selection.generation();
      }
      var previous =
          cameras.getOrDefault(
              observation.cameraName(),
              new CameraStatus(
                  Double.NEGATIVE_INFINITY,
                  Double.NEGATIVE_INFINITY,
                  Double.NEGATIVE_INFINITY,
                  0,
                  0,
                  false,
                  "Waiting"));
      cameras.put(
          observation.cameraName(),
          new CameraStatus(
              operational ? sample.captureFpgaSeconds() : previous.lastObservation(),
              accepted ? sample.captureFpgaSeconds() : previous.lastAccepted(),
              previous.lastFused(),
              previous.accepted() + (accepted ? 1 : 0),
              previous.rejected() + (accepted ? 0 : 1),
              operational
                  || (previous.usable()
                      && !Sets.immutableEnumSet(
                              VisionProcessor.Reason.CONFIGURATION,
                              VisionProcessor.Reason.CALIBRATION,
                              VisionProcessor.Reason.MALFORMED,
                              VisionProcessor.Reason.TIMESTAMP)
                          .contains(decision.reason())),
              decision.reason().name()));
      if (accepted) {
        var measurement = decision.measurement().orElseThrow();
        hasSeenTag = true;
        lastTag = now;
        if (measurement.tagIds().stream().anyMatch(hubTags()::contains)) lastHub = now;
        if (fusion) queue.add(measurement);
      }
    }
    if (!available) {
      queue.clearPending();
      retireObservations();
    }
    int configured = 0, usable = 0, required = 0;
    boolean all = true;
    for (var camera : profile.cameras()) {
      if (!camera.enabled()) continue;
      configured++;
      if (camera.required()) required++;
      var previous =
          cameras.getOrDefault(
              camera.name(),
              new CameraStatus(
                  Double.NEGATIVE_INFINITY,
                  Double.NEGATIVE_INFINITY,
                  Double.NEGATIVE_INFINITY,
                  0,
                  0,
                  false,
                  "No fresh frame"));
      boolean valid = available && previous.usable() && now - previous.lastObservation() <= .5;
      if (valid) {
        usable++;
        pending = false;
      }
      if (camera.required() && !valid) all = false;
      cameras.put(
          camera.name(),
          new CameraStatus(
              previous.lastObservation(),
              previous.lastAccepted(),
              previous.lastFused(),
              previous.accepted(),
              previous.rejected(),
              valid,
              previous.reason()));
    }
    if (fusion)
      prepared =
          VisionProcessor.accountForCorrelation(queue.release(now, 32), Math.max(1, configured));
    String reason =
        configured == 0
            ? "No measured camera configuration"
            : !ack.tagSelectionSupported() && ack.applied()
                ? "Spot service does not support tag selection"
                : !available
                    ? health.reason()
                    : hubTags().isEmpty() && getState() != VisionState.TAGS
                        ? "Waiting for alliance or complete hub layout"
                        : pending ? "Waiting for tag selection application" : "Ready";
    status =
        new Status(
            available && configured > 0,
            reason,
            configured,
            usable,
            required,
            configured > 0 && all,
            selection.generation(),
            appliedSelection != selection.generation(),
            queue.size(),
            queue.lateCount() + queue.overloadCount(),
            generation,
            cameras);
  }

  public List<VisionMeasurement> drainMeasurements() {
    var result = prepared;
    prepared = ImmutableList.of();
    result.forEach(value -> offered.put(value.frameId(), value));
    return result;
  }

  /** Ingestion recheck; no old prepared result survives a reset or policy change. */
  public boolean eligible(VisionMeasurement value, double timestamp) {
    return value.equals(offered.get(value.frameId()))
        && value.timestamp() > resetTime
        && timestamp - value.timestamp() <= profile.maxAgeS()
        && value.timestamp() <= timestamp + profile.futureToleranceS()
        && status.available()
        && value.tagIds().stream().allMatch(selection.allowedTagIds()::contains);
  }

  public VisionState getState() {
    return state;
  }

  public Status getStatus() {
    return status;
  }

  public boolean hasSeenTag() {
    return hasSeenTag;
  }

  public void hubTagsRequest() {
    if (getState() == VisionState.TAGS) setStateFromRequest(VisionState.WAITING_FOR_HUB_TAGS);
  }

  public void measurementFused(VisionMeasurement value) {
    if (!eligible(value, now)) return;
    offered.remove(value.frameId());
    io.measurementFused(value);
    var previous = cameras.get(value.source());
    if (previous != null)
      cameras.put(
          value.source(),
          new CameraStatus(
              previous.lastObservation(),
              previous.lastAccepted(),
              Math.max(previous.lastFused(), value.timestamp()),
              previous.accepted(),
              previous.rejected(),
              previous.usable(),
              previous.reason()));
    refreshStatus();
  }

  public void reset(double timestamp) {
    prepared = ImmutableList.of();
    offered.clear();
    queue.reset(timestamp);
    processor.reset(timestamp);
    history.reset();
    io.reset(timestamp);
    resetTime = timestamp;
    appliedSelection = 0;
    retireObservations();
    refreshStatus();
  }

  public void robotPeriodic() {
    if (!closed) {
      setStateFromRequest(getNextState(state));
      whileInState(state);
    }
  }

  public boolean seeingTag() {
    return now - lastTag <= profile.maxAgeS();
  }

  public void tagsRequest() {
    setStateFromRequest(VisionState.TAGS);
  }

  public double tickTime() {
    return now;
  }

  public void whileInState(VisionState state) {
    if (closed) return;
    var desired = new HashSet<String>();
    if (!status.available()) desired.add("Spot: " + status.reason());
    for (var camera : profile.cameras()) {
      var observed = cameras.get(camera.name());
      if (camera.enabled() && camera.required() && (observed == null || !observed.usable()))
        desired.add("Spot required camera unavailable: " + camera.name());
    }
    for (var fault : desired) if (faults.add(fault)) BenchLog.logFault(fault);
    for (var fault : Set.copyOf(faults))
      if (!desired.contains(fault)) {
        BenchLog.clearFault(fault);
        faults.remove(fault);
      }
    BenchLog.log("Vision/Spot/Available", status.available());
    BenchLog.log("Vision/Spot/Reason", status.reason());
    BenchLog.log("Vision/Spot/UsableCameras", status.usable());
    BenchLog.log("Vision/Spot/QueueDrops", status.queueDrops());
    BenchLog.log("Vision/Spot/SelectionGeneration", selection.generation());
    for (var entry : cameras.entrySet()) {
      String path = "Vision/Spot/" + entry.getKey();
      var value = entry.getValue();
      BenchLog.log(path + "/Accepted", value.accepted());
      BenchLog.log(path + "/Rejected", value.rejected());
      BenchLog.log(path + "/LastFusedFpgaS", value.lastFused());
      BenchLog.log(path + "/LastObservationFpgaS", value.lastObservation());
    }
    io.publishDecisions(now);
  }

  private List<Integer> broadTags() {
    return profile.field().tags().stream().map(FieldTag::id).sorted().toList();
  }

  private Set<Integer> hubTags() {
    if (currentAlliance.isEmpty()) return ImmutableSet.of();
    var ids = currentAlliance.orElseThrow() == Alliance.Red ? RED_HUB : BLUE_HUB;
    // An incomplete layout cannot claim alliance-hub support.
    return broadTags().containsAll(ids) ? ids : ImmutableSet.of();
  }

  private void refreshStatus() {
    int usable = (int) cameras.values().stream().filter(CameraStatus::usable).count();
    boolean all =
        profile.cameras().stream()
            .filter(c -> c.enabled() && c.required())
            .allMatch(c -> cameras.containsKey(c.name()) && cameras.get(c.name()).usable());
    status =
        new Status(
            status.available(),
            appliedSelection == selection.generation()
                ? status.reason()
                : "Waiting for tag selection application",
            status.configured(),
            usable,
            status.required(),
            status.configured() > 0 && all,
            selection.generation(),
            appliedSelection != selection.generation(),
            queue.size(),
            status.queueDrops(),
            generation,
            cameras);
  }

  private void retireObservations() {
    cameras.replaceAll((name, old) ->
        new CameraStatus(
            Double.NEGATIVE_INFINITY,
            Double.NEGATIVE_INFINITY,
            Double.NEGATIVE_INFINITY,
            old.accepted(),
            old.rejected(),
            false,
            "Retired generation"));
    lastHub = lastTag = Double.NEGATIVE_INFINITY;
  }

  private void select(List<Integer> ids) {
    if (ids.equals(selection.allowedTagIds())) return;
    selection = new VisionIO.TagSelection(selection.generation() + 1, ids);
    prepared = ImmutableList.of();
    offered.clear();
    queue.clearPending();
    double acquired = lastHub;
    retireObservations();
    if (getState() == VisionState.HUB_TAGS) lastHub = acquired;
    appliedSelection = 0;
    io.setTagSelection(selection);
    refreshStatus();
  }

  private void setStateFromRequest(VisionState next) {
    if (next == state) return;
    state = next;
    afterTransition(next);
  }

  protected void afterTransition(VisionState state) {
    select(state == VisionState.HUB_TAGS ? hubTags().stream().sorted().toList() : broadTags());
  }

  protected VisionState getNextState(VisionState state) {
    if (state == VisionState.TAGS) return state;
    return !hubTags().isEmpty() && now - lastHub < .5
        ? VisionState.HUB_TAGS
        : VisionState.WAITING_FOR_HUB_TAGS;
  }
}
