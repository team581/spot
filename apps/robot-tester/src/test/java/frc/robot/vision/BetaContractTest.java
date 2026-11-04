package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.data.Offset.offset;

import com.google.common.collect.ImmutableList;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.math.geometry.Rotation2d;
import edu.wpi.first.math.geometry.Rotation3d;
import edu.wpi.first.math.geometry.Transform3d;
import edu.wpi.first.math.geometry.Translation3d;
import edu.wpi.first.networktables.TimestampedRaw;
import frc.robot.vision.generated.SpotProtos;
import frc.robot.vision.results.VisionMeasurement;
import java.io.IOException;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

final class BetaContractTest {
  private static SpotProtos.Acknowledgement ack() throws IOException {
    return SpotProtos.Acknowledgement.parseFrom(fixture("ack"));
  }

  private static byte[] fixture(String name) throws IOException {
    try (var input = BetaContractTest.class.getResourceAsStream("/spot-beta/" + name + ".bin")) {
      if (input == null) {
        throw new IOException("fixture missing: " + name);
      }
      return input.readAllBytes();
    }
  }

  private static SpotProtos.Manifest manifest() throws IOException {
    return SpotProtos.Manifest.parseFrom(fixture("manifest"));
  }

  private static VisionMeasurement measurement(String source, double timestamp) {
    return new VisionMeasurement(
        source,
        source + timestamp,
        Pose2d.kZero,
        timestamp,
        .1,
        .1,
        1e6,
        ImmutableList.of(1),
        .1,
        1.);
  }

  private static VisionProcessor processor() throws IOException {
    var mount = new Transform3d(new Translation3d(.2, 0, .5), new Rotation3d());
    return new VisionProcessor(
        manifest().getProfile(),
        ImmutableList.of(SpotCameraProfiles.Camera.fixed("front", mount)),
        timestamp ->
            Optional.of(
                new VisionProcessor.CaptureState(
                    new Pose2d(2, 0, Rotation2d.kZero), 1., 0., 0., 0., 0.)),
        VisionProcessor.Policy.conservative());
  }

  private static VisionIO.Sample sample(String name) throws IOException {
    return new VisionIO.Sample(SpotProtos.Observation.parseFrom(fixture(name)), 10.05);
  }

  @Test
  void additivePolicyBytesAgreeWithoutChangingLegacyFixtures() throws IOException {
    var bytes = fixture("policy-state");
    assertThat(java.util.HexFormat.of().formatHex(bytes))
        .isEqualTo("0a07726f626f742d311001180720032a020102");
    var state = SpotProtos.RobotState.parseFrom(bytes);
    assertThat(state.getTagSelectionGeneration()).isEqualTo(3);
    assertThat(state.getAllowedTagIdsList()).containsExactly(1, 2);
    assertThat(state.toByteArray()).containsExactly(bytes);
    var ack = SpotProtos.Acknowledgement.parseFrom(fixture("policy-ack"));
    assertThat(ack.getTagSelectionSupported()).isTrue();
    assertThat(ack.toBuilder().clearTagSelectionSupported().build().toByteArray())
        .containsExactly(fixture("ack"));
    var observation = SpotProtos.Observation.parseFrom(fixture("policy-multi"));
    assertThat(observation.getTagSelectionGeneration()).isEqualTo(3);
    assertThat(observation.toBuilder().clearTagSelectionGeneration().build().toByteArray())
        .containsExactly(fixture("multi"));
  }

  @Test
  void correlatedMeasurementsInflateUncertaintyAndCannotImproveTrustByCameraCount() {
    var result =
        VisionProcessor.accountForCorrelation(
            ImmutableList.of(measurement("a", 10.), measurement("b", 10.)));
    assertThat(result.get(0).stdX()).isGreaterThan(.1);
    var trust = new TrustFactor();
    trust.ingest(ImmutableList.of(result.get(0)));
    double before = trust.get();
    trust.ingest(result);
    assertThat(trust.get()).isEqualTo(before);
    trust.ingest(ImmutableList.of());
    assertThat(trust.get()).isEqualTo(before);
    trust.updateOdometry(1., .02, false);
    assertThat(trust.get()).isGreaterThan(before);
  }

  @CsvSource({".0003125, 4.", ".00125, 4.", ".005, 2.", ".02, 1.", ".08, 1."})
  @ParameterizedTest
  void imageAreaConditioningKeepsUncertaintyWithinItsIntendedBounds(
      double imageAreaFraction, double expectedFactor) throws IOException {
    var observation = sample("multi").observation().toBuilder().setTimestampUncertaintyS(1e-12);
    observation.getCandidatesBuilder(0).setImageAreaFraction(.02);
    var baseline =
        processor()
            .process(new VisionIO.Sample(observation.build(), 10.05), ack(), 10.1, false)
            .measurement()
            .orElseThrow();
    observation.getCandidatesBuilder(0).setImageAreaFraction(imageAreaFraction);
    var result =
        processor().process(new VisionIO.Sample(observation.build(), 10.05), ack(), 10.1, false);
    assertThat(result.reason()).isEqualTo(VisionProcessor.Reason.ACCEPTED);
    assertThat(result.measurement().orElseThrow().stdX())
        .isCloseTo(baseline.stdX() * expectedFactor, offset(1e-9));
  }

  @Test
  void immutableMeasurementOwnsTagsAndDeviationVector() {
    var tags = new java.util.ArrayList<Integer>();
    tags.add(1);
    var result =
        new VisionMeasurement(
            "front", "one", new Pose2d(2, 3, Rotation2d.kZero), 10., .1, .2, 1e6, tags, 0., 0.);
    tags.add(2);
    assertThat(result.tagIds()).containsExactly(1);
    result.standardDevs().set(0, 0, 55.);
    assertThat(result.standardDevs().get(0, 0)).isEqualTo(.1);
  }

  @Test
  void ippeSelectionUsesCaptureHeadingAndRejectsUndecidableTranslation() throws IOException {
    assertThat(processor().process(sample("ippe"), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.ACCEPTED);
    assertThat(processor().process(sample("ambiguous"), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.AMBIGUOUS);
    assertThat(processor().process(sample("empty"), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.NO_TAGS);
  }

  @Test
  void missingHistoryNeverSubstitutesCurrentPoseOrJointAngle() throws IOException {
    var processor =
        new VisionProcessor(
            manifest().getProfile(),
            ImmutableList.of(),
            timestamp -> Optional.empty(),
            VisionProcessor.Policy.conservative());
    assertThat(processor.process(sample("multi"), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.HISTORY);
    processor =
        new VisionProcessor(
            manifest().getProfile(),
            ImmutableList.of(new SpotCameraProfiles.Camera("front", null, null)),
            timestamp -> Optional.of(new VisionProcessor.CaptureState(Pose2d.kZero, 0, 0, 0, 0, 0)),
            VisionProcessor.Policy.conservative());
    assertThat(processor.process(sample("multi"), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.MOUNT_HISTORY);
  }

  @Test
  void olderQueuedFusionCannotMarkANewerRejectedFrameAsFused() {
    var latest = new java.util.HashMap<String, Object>();
    latest.put("frame_id", "new-accepted-frame");
    latest.put("fused", false);
    SpotVisionIO.markDecisionFused(latest, "old-accepted-frame");
    assertThat(latest).containsEntry("fused", false);
    latest.put("frame_id", "");
    SpotVisionIO.markDecisionFused(latest, "old-accepted-frame");
    assertThat(latest).containsEntry("fused", false);
    latest.put("frame_id", "current-accepted-frame");
    SpotVisionIO.markDecisionFused(latest, "current-accepted-frame");
    assertThat(latest).containsEntry("fused", true);
  }

  @Test
  void pythonAndJavaAgreeOnPacketsHashesAndCoordinateUnits() throws IOException {
    var manifest = manifest();
    assertThat(manifest.toByteArray()).containsExactly(fixture("manifest"));
    assertThat(SpotProtocol.hash(manifest.getProfile())).isEqualTo(manifest.getManifestHash());
    assertThat(SpotProtocol.hash(manifest.getProfile().getField())).isEqualTo(ack().getFieldHash());
    for (String name : ImmutableList.of("empty", "multi", "ippe", "ambiguous")) {
      assertThat(sample(name).observation().toByteArray()).containsExactly(fixture(name));
    }
    var accepted = processor().process(sample("multi"), ack(), 10.1, false);
    assertThat(accepted.reason()).isEqualTo(VisionProcessor.Reason.ACCEPTED);
    var measurement = accepted.measurement().orElseThrow();
    assertThat(measurement.pose().getX()).isCloseTo(2., offset(1e-12));
    assertThat(measurement.pose().getY()).isCloseTo(0., offset(1e-12));
    assertThat(measurement.timestamp()).isEqualTo(10.05);
    assertThat(measurement.stdX()).isPositive();
    assertThat(measurement.stdHeading()).isEqualTo(1e6);
  }

  @Test
  void reorderWindowSpansLoopsAndDoesNotWaitForOfflineCamera() {
    var queue = new MeasurementQueue(.02, 8);
    queue.add(measurement("fast", 10.));
    assertThat(queue.release(10.01, 32)).isEmpty();
    queue.add(measurement("slow", 9.99));
    assertThat(queue.release(10.03, 32).stream().map(VisionMeasurement::timestamp))
        .containsExactly(9.99, 10.);
    assertThat(queue.add(measurement("late", 9.98))).isFalse();
    assertThat(queue.lateCount()).isEqualTo(1);
    queue.reset(11.);
    assertThat(queue.add(measurement("pre-reset", 10.99))).isFalse();
  }

  @Test
  void repeatedFramesDoNotManufactureAdditionalCameraSources() {
    var frames = new java.util.ArrayList<VisionMeasurement>();
    for (int i = 0; i < 8; i++) frames.add(measurement("front", 10. + i * .001));
    var batch = VisionProcessor.accountForCorrelation(frames, 4);
    assertThat(batch).allMatch(value -> value.stdX() == .2);
    assertThat(VisionProcessor.accountForCorrelation(frames.subList(0, 4), 4))
        .allMatch(value -> value.stdX() == .2);
  }

  @Test
  void sourceCountFloorCoversCorrelatedCamerasSplitAcrossReleaseBatches() {
    var value =
        new VisionMeasurement(
            "front", "one", Pose2d.kZero, 1, .1, .1, 1e6, ImmutableList.of(1), 0, 0);
    var released = VisionProcessor.accountForCorrelation(ImmutableList.of(value), 4);
    assertThat(released.get(0).stdX()).isEqualTo(.2);
    assertThat(value.stdX()).isEqualTo(.1);
  }

  @Test
  void staleFutureMalformedGenerationDuplicateAndResetPacketsFailClosed() throws IOException {
    var processor = processor();
    assertThat(processor.process(sample("multi"), ack(), 10.4, false).reason())
        .isEqualTo(VisionProcessor.Reason.STALE);
    assertThat(processor.process(sample("multi"), ack(), 10., false).reason())
        .isEqualTo(VisionProcessor.Reason.FUTURE);
    var observation = sample("multi").observation().toBuilder().setSchemaVersion(99).build();
    assertThat(
            processor.process(new VisionIO.Sample(observation, 10.05), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.SCHEMA);
    observation = sample("multi").observation().toBuilder().setRuntimeGeneration("old").build();
    assertThat(
            processor.process(new VisionIO.Sample(observation, 10.05), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.CONFIGURATION);
    assertThat(processor.process(sample("multi"), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.ACCEPTED);
    assertThat(processor.process(sample("multi"), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.DUPLICATE);
    processor.reset(10.06);
    assertThat(processor.process(sample("multi"), ack(), 10.1, false).reason())
        .isEqualTo(VisionProcessor.Reason.RESET);
  }

  @Test
  void timestampDomainsHandleSentinelsAndRejectUnverifiedClientEpoch() {
    var remote = new TimestampedRaw(10_050_000, 10_050_000, new byte[0]);
    assertThat(SpotVisionIO.captureTimestamp(remote, true).orElseThrow()).isEqualTo(10.05);
    for (long sentinel : ImmutableList.of(0L, 1L)) {
      assertThat(
              SpotVisionIO.captureTimestamp(
                      new TimestampedRaw(10_050_000, sentinel, new byte[0]), true)
                  .orElseThrow())
          .isEqualTo(10.05);
    }
    assertThat(SpotVisionIO.captureTimestamp(remote, false)).isEmpty();
    assertThat(
            SpotVisionIO.captureTimestamp(
                new TimestampedRaw(10_050_000, 99_000_000, new byte[0]), true))
        .isEmpty();
  }

  @Test
  void transformedCameraMountUsesNwuAndInverseComposition() {
    var robot = new Pose3d(2, 3, .1, new Rotation3d(0, 0, Math.PI / 2));
    var mount = new Transform3d(new Translation3d(.2, -.3, .5), new Rotation3d(.1, -.2, .3));
    var recovered =
        SpotProtocol.pose(SpotProtocol.pose(robot.transformBy(mount))).transformBy(mount.inverse());
    assertThat(recovered.getTranslation().getDistance(robot.getTranslation())).isLessThan(1e-12);
    assertThat(recovered.getRotation().minus(robot.getRotation()).getAngle()).isLessThan(1e-12);
  }
}
