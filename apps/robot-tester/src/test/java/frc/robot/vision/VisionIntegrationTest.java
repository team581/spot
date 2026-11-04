package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.data.Offset.offset;

import edu.wpi.first.hal.HAL;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.math.geometry.Rotation2d;
import edu.wpi.first.math.geometry.Rotation3d;
import edu.wpi.first.math.geometry.Transform3d;
import edu.wpi.first.math.geometry.Translation3d;
import edu.wpi.first.wpilibj.DriverStation.Alliance;
import frc.robot.vision.generated.SpotProtos;
import frc.robot.vision.results.VisionMeasurement;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

final class VisionIntegrationTest {
  static final class FakeIO implements VisionIO {
    SpotProtos.Acknowledgement ack;
    TagSelection selection;
    boolean available = true;
    int reads, closed;
    Runnable duringRead = () -> {};
    final List<Sample> samples = new ArrayList<>();
    final List<VisionMeasurement> fused = new ArrayList<>();
    final List<VisionProcessor.Reason> reasons = new ArrayList<>();

    @Override
    public void close() {
      closed++;
    }

    @Override
    public void measurementFused(VisionMeasurement value) {
      fused.add(value);
    }

    @Override
    public Inputs readInputs(double now, boolean enabled) {
      reads++;
      duringRead.run();
      var result = new Inputs(new Health(available, available ? "Ready" : "Offline", ack), samples);
      samples.clear();
      return result;
    }

    @Override
    public void reportDecision(Sample sample, VisionProcessor.Decision decision) {
      reasons.add(decision.reason());
    }

    @Override
    public void setTagSelection(TagSelection value) {
      selection = value;
    }
  }

  /** These mounts and optical modes are deliberately synthetic, never production settings. */
  static final class Fixture implements AutoCloseable {
    double time = 10.;
    boolean operator = true;
    Optional<Alliance> alliance = Optional.of(Alliance.Red);
    final Pose2d robot = new Pose2d(4, 4, Rotation2d.kZero);
    final List<SpotCameraProfiles.Camera> mounts = new ArrayList<>();
    final FakeIO io = new FakeIO();
    final SpotProtos.Profile profile;
    final Vision vision;
    long sequence;

    Fixture(boolean fusion) {
      var field =
          SpotProtos.FieldLayout.newBuilder()
              .setOrigin("blue-wall-right")
              .setLengthM(16)
              .setWidthM(8);
      for (int id : Set.of(1, 2, 3, 4, 5, 8, 9, 10, 11, 18, 19, 20, 21, 24, 25, 26, 27)) {
        int direction =
            switch (id) {
              case 2, 8, 18, 24 -> 0;
              case 3, 9, 19, 25 -> 1;
              case 5, 11, 21, 27 -> 3;
              default -> 2;
            };
        double x = new double[] {4, 4, 7, 1}[direction], y = new double[] {7, 1, 4, 4}[direction];
        field.addTags(
            SpotProtos.FieldTag.newBuilder()
                .setId(id)
                .setSizeM(.1651)
                .setFieldToTag(SpotProtos.Pose.newBuilder().setXM(x).setYM(y).setZM(1).setQw(1)));
      }
      var builder =
          SpotProtos.Profile.newBuilder()
              .setSchemaVersion(2)
              .setRobotId("synthetic")
              .setField(field)
              .setFusionEnabled(fusion)
              .setRevisedTrustEnabled(true)
              .setMaxAgeS(.25)
              .setFutureToleranceS(.005)
              .setReorderWindowS(.02);
      int index = 0;
      for (String name : SpotCameraProfiles.CAMERA_NAMES) {
        double yaw = new double[] {Math.PI / 2, -Math.PI / 2, 0, Math.PI}[index];
        var mount =
            new Transform3d(new Translation3d(.1 * index, .1, .5), new Rotation3d(0, 0, yaw));
        mounts.add(SpotCameraProfiles.Camera.fixed(name, mount));
        index++;
        builder.addCameras(
            SpotProtocol.camera(name, mount)
                .setRequired(true)
                .addAllowedModes(
                    SpotProtos.OpticalMode.newBuilder()
                        .setId("synthetic-mode")
                        .setWidth(640)
                        .setHeight(480)
                        .setFps(30)
                        .setPixelFormat("YUYV")
                        .setOpticalSignature("synthetic-lens")));
      }
      profile = builder.build();
      var ack =
          SpotProtos.Acknowledgement.newBuilder()
              .setSchemaVersion(2)
              .setRobotId("synthetic")
              .setRobotSession("robot")
              .setServiceSession("service")
              .setManifestHash(SpotProtocol.hash(profile))
              .setFieldHash(SpotProtocol.hash(profile.getField()))
              .setRuntimeGeneration("runtime")
              .setConnectionEpoch(1)
              .setSyncEpoch(1)
              .setApplied(true)
              .setTagSelectionSupported(true);
      for (var camera : profile.getCamerasList())
        ack.addCameras(
            SpotProtos.CameraGeneration.newBuilder()
                .setCameraName(camera.getName())
                .setBindingId(camera.getName())
                .setBindingGeneration(1)
                .setCalibrationHash("calibration")
                .setCalibrationValid(true)
                .setModeId("synthetic-mode")
                .setOpticalSignature("synthetic-lens"));
      io.ack = ack.build();
      vision =
          new Vision(
              io,
              profile,
              mounts,
              new Vision.CaptureSource() {
                @Override
                public VisionProcessor.CaptureState current(double now) {
                  return new VisionProcessor.CaptureState(robot, 0, 0, 0, 0, 0);
                }

                @Override
                public Optional<Pose2d> poseAt(double now) {
                  return Optional.of(robot);
                }
              },
              () -> time,
              () -> true,
              () -> operator,
              () -> alliance);
      vision.collectInputs();
    }

    @Override
    public void close() {
      vision.close();
    }

    void frame(String camera, int tag, double capture) {
      frame(camera, tag, capture, io.selection.generation());
    }

    void frame(String camera, int tag, double capture, long selectionGeneration) {
      var mount =
          mounts.stream()
              .filter(item -> item.name().equals(camera))
              .findFirst()
              .orElseThrow()
              .mount();
      var frame =
          SpotProtos.Observation.newBuilder()
              .setSchemaVersion(2)
              .setRobotId("synthetic")
              .setRobotSession("robot")
              .setServiceSession(io.ack.getServiceSession())
              .setCaptureEpoch("capture")
              .setConnectionEpoch(io.ack.getConnectionEpoch())
              .setSyncEpoch(io.ack.getSyncEpoch())
              .setSequence(++sequence)
              .setCameraName(camera)
              .setBindingId(camera)
              .setBindingGeneration(1)
              .setManifestHash(io.ack.getManifestHash())
              .setFieldHash(io.ack.getFieldHash())
              .setCalibrationHash("calibration")
              .setCalibrationValid(true)
              .setRuntimeGeneration(io.ack.getRuntimeGeneration())
              .setModeId("synthetic-mode")
              .setOpticalSignature("synthetic-lens")
              .setTimestampSource("read-completion-local-nt")
              .setTimestampUncertaintyS(.001)
              .setTagSelectionGeneration(selectionGeneration);
      if (tag > 0) {
        int companion =
            switch (tag) {
              case 1 -> 10;
              case 2 -> 8;
              case 3 -> 9;
              case 4 -> 10;
              case 5 -> 11;
              case 18 -> 24;
              case 19 -> 25;
              case 20 -> 26;
              case 21 -> 27;
              default -> 1;
            };
        frame.addTags(
            SpotProtos.TagObservation.newBuilder()
                .setId(companion)
                .setUsedForPose(true)
                .addAllCornersXyPx(List.of(3., 1., 4., 1., 4., 2., 3., 2.)));
        frame.addTags(
            SpotProtos.TagObservation.newBuilder()
                .setId(tag)
                .setUsedForPose(true)
                .addAllCornersXyPx(List.of(1., 1., 2., 1., 2., 2., 1., 2.)));
        frame.addCandidates(
            SpotProtos.PoseCandidate.newBuilder()
                .setFieldToCamera(SpotProtocol.pose(new Pose3d(robot).transformBy(mount)))
                .setMethod(SpotProtos.PoseCandidate.Method.MULTI_TAG_SQPNP)
                .addTagIds(tag)
                .addTagIds(companion)
                .setAverageTagDistanceM(2)
                .setReprojectionErrorPx(.1)
                .setImageAreaFraction(.02)
                .setImageSpreadFraction(.1));
      }
      io.samples.add(new VisionIO.Sample(frame.build(), capture));
    }

    void tick(double now) {
      time = now;
      vision.collectInputs();
      vision.robotPeriodic();
    }
  }

  @Test void inputCollectionDelayDoesNotMakeArrivingFramesAppearFuture() {
    try (var f = new Fixture(false)) {
      f.io.duringRead = () -> f.time += .030;
      f.frame("front", 0, f.time + .010);
      f.vision.collectInputs();
      assertThat(f.io.reasons).containsExactly(VisionProcessor.Reason.NO_TAGS);
      // A genuinely future timestamp still fails the unchanged tolerance gate.
      f.frame("front", 0, f.time + .100);
      f.vision.collectInputs();
      assertThat(f.io.reasons.get(f.io.reasons.size() - 1)).isEqualTo(VisionProcessor.Reason.FUTURE);
    }
  }

  @BeforeAll
  static void hal() {
    HAL.initialize(500, 0);
  }

  @Test
  void fourStaticCamerasRecoverSamePoseAndDrainOnce() {
    try (var f = new Fixture(true)) {
      assertThat(f.profile.getCamerasList().stream().map(SpotProtos.CameraDefinition::getName))
          .containsExactly("left", "right", "front", "back");
      for (int i = 0; i < 4; i++)
        f.frame(SpotCameraProfiles.CAMERA_NAMES.get(i), new int[] {2, 3, 1, 5}[i], 10.01);
      f.tick(10.04);
      var batch = f.vision.drainMeasurements();
      assertThat(batch).hasSize(4);
      assertThat(f.vision.drainMeasurements()).isEmpty();
      for (var value : batch) {
        assertThat(value.pose().getX()).isCloseTo(4., offset(1e-10));
        assertThat(value.pose().getY()).isCloseTo(4., offset(1e-10));
        assertThat(value.timestamp()).isEqualTo(10.01);
        assertThat(value.stdHeading()).isEqualTo(2e6);
        assertThat(f.vision.eligible(value, 10.04)).isTrue();
        f.vision.measurementFused(value);
        f.vision.measurementFused(value);
      }
      assertThat(f.io.fused).hasSize(4);
      int reads = f.io.reads;
      assertThat(f.vision.getStatus().allRequiredHealthy()).isTrue();
      f.vision.getStatus();
      f.vision.seeingTag();
      assertThat(f.io.reads).isEqualTo(reads);
      f.tick(10.06);
      assertThat(f.vision.drainMeasurements()).isEmpty();
      f.vision.close();
      f.vision.close();
      assertThat(f.io.closed).isEqualTo(1);
    }
  }

  @Test
  void hubAcquisitionHandoffLossAndRepeatedRequestsUseOneGlobalPolicy() {
    try (var f = new Fixture(false)) {
      f.vision.hubTagsRequest();
      assertThat(f.vision.getState()).isEqualTo(VisionState.WAITING_FOR_HUB_TAGS);
      f.frame("back", 21, 10.01);
      f.tick(10.04);
      assertThat(f.vision.getState()).isEqualTo(VisionState.WAITING_FOR_HUB_TAGS);
      f.frame("left", 2, 10.05);
      f.tick(10.08);
      assertThat(f.vision.getState()).isEqualTo(VisionState.HUB_TAGS);
      assertThat(f.io.selection.allowedTagIds()).containsExactly(2, 3, 4, 5, 8, 9, 10, 11);
      long generation = f.io.selection.generation();
      f.vision.hubTagsRequest();
      f.tick(10.3);
      assertThat(f.io.selection.generation()).isEqualTo(generation);
      assertThat(f.vision.getState()).isEqualTo(VisionState.HUB_TAGS);
      f.frame("right", 3, 10.32);
      f.tick(10.34);
      f.tick(10.6);
      assertThat(f.vision.getState()).isEqualTo(VisionState.HUB_TAGS);
      f.tick(10.85);
      assertThat(f.vision.getState()).isEqualTo(VisionState.WAITING_FOR_HUB_TAGS);
      f.vision.tagsRequest();
      assertThat(f.vision.getState()).isEqualTo(VisionState.TAGS);
      assertThat(f.vision.drainMeasurements()).isEmpty(); // shadow cannot fuse
    }
  }

  @Test
  void oldPolicyExcludedIdsAndRejectedObservationsCannotAcquireHub() {
    try (var f = new Fixture(false)) {
      f.vision.hubTagsRequest();
      f.frame("left", 2, 9.5);
      f.tick(10.04);
      assertThat(f.vision.getState()).isEqualTo(VisionState.WAITING_FOR_HUB_TAGS);
      f.frame("front", 4, 10.05);
      f.tick(10.08);
      f.frame("front", 20, 10.09); // current generation with forbidden candidate
      f.frame("left", 2, 10.09, 1); // in-flight previous policy
      f.tick(10.12);
      assertThat(f.io.reasons.subList(f.io.reasons.size() - 2, f.io.reasons.size()))
          .containsExactly(VisionProcessor.Reason.TAG_POLICY, VisionProcessor.Reason.TAG_POLICY);
      f.tick(10.59);
      assertThat(f.vision.getState()).isEqualTo(VisionState.WAITING_FOR_HUB_TAGS);
    }
  }

  @Test
  void suppressionDisconnectGenerationAndResetInvalidatePendingOrReleasedFrames() {
    try (var f = new Fixture(true)) {
      f.frame("front", 1, 10.01);
      f.tick(10.02);
      assertThat(f.vision.getStatus().queueDepth()).isEqualTo(1);
      f.operator = false;
      f.tick(10.04);
      assertThat(f.vision.drainMeasurements()).isEmpty();
      f.operator = true;
      f.frame("front", 1, 10.05);
      f.tick(10.06);
      f.io.available = false;
      f.tick(10.08);
      assertThat(f.vision.drainMeasurements()).isEmpty();
      f.io.available = true;
      f.frame("front", 1, 10.09);
      f.tick(10.10);
      f.io.ack = f.io.ack.toBuilder().setRuntimeGeneration("new-runtime").build();
      f.tick(10.12);
      assertThat(f.vision.drainMeasurements()).isEmpty();
      f.frame("front", 1, 10.13);
      f.tick(10.16);
      var value = f.vision.drainMeasurements().get(0);
      f.vision.reset(10.16);
      assertThat(f.vision.eligible(value, 10.16)).isFalse();
      f.vision.measurementFused(value);
      assertThat(f.io.fused).isEmpty();
      f.frame("front", 1, 10.15);
      f.tick(10.18);
      assertThat(f.vision.drainMeasurements()).isEmpty();
      assertThat(f.io.reasons).contains(VisionProcessor.Reason.RESET);
      f.io.ack = f.io.ack.toBuilder().setTagSelectionSupported(false).build();
      f.tick(10.2);
      assertThat(f.vision.getStatus().available()).isFalse();
    }
  }

  @Test
  void unknownAllianceStaysBroadAndChangingAllianceReacquires() {
    try (var f = new Fixture(false)) {
      f.alliance = Optional.empty();
      f.vision.hubTagsRequest();
      f.frame("front", 4, 10.01);
      f.tick(10.04);
      assertThat(f.vision.getState()).isEqualTo(VisionState.WAITING_FOR_HUB_TAGS);
      assertThat(f.io.selection.allowedTagIds()).contains(1, 18, 27);
      f.alliance = Optional.of(Alliance.Blue);
      f.tick(10.06);
      f.frame("back", 21, 10.07);
      f.tick(10.10);
      assertThat(f.io.selection.allowedTagIds()).containsExactly(18, 19, 20, 21, 24, 25, 26, 27);
      f.alliance = Optional.of(Alliance.Red);
      f.tick(10.12);
      assertThat(f.vision.getState()).isEqualTo(VisionState.WAITING_FOR_HUB_TAGS);
      assertThat(f.io.selection.allowedTagIds()).contains(1, 18, 2);
    }
  }

  @Test
  void zeroTagFramesAreHealthyButPoseTrustIsIndependent() {
    try (var f = new Fixture(false)) {
      for (var name : SpotCameraProfiles.CAMERA_NAMES) f.frame(name, 0, 10.01);
      f.tick(10.04);
      assertThat(f.vision.getStatus().usable()).isEqualTo(4);
      assertThat(f.vision.getStatus().allRequiredHealthy()).isTrue();
      assertThat(f.vision.seeingTag()).isFalse();
      f.tick(10.53);
      assertThat(f.vision.getStatus().usable()).isEqualTo(0);
      assertThat(f.vision.getStatus().allRequiredHealthy()).isFalse();
    }
  }
}
