package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;
import edu.wpi.first.hal.HAL;
import edu.wpi.first.math.geometry.Pose2d;
import edu.wpi.first.math.geometry.Rotation2d;
import frc.robot.localization.Localization;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

class BenchLocalizationTest {
  @BeforeAll static void initialize() { HAL.initialize(500, 0); }

  @Test void stationaryEstimatorConsumesOnceAndTrustOnlyFollowsActualIngestion() {
    try (var fixture = new VisionIntegrationTest.Fixture(true)) {
      var localization = new Localization(fixture.robot, 10.);
      localization.updateOdometry(10.);
      assertThat(localization.trust().get()).isInfinite();
      fixture.frame("front", 1, 10.01);
      fixture.tick(10.04);
      localization.updateOdometry(10.04);
      assertThat(localization.ingest(fixture.vision, 10.04)).hasSize(1);
      assertThat(localization.consumed()).isEqualTo(1);
      assertThat(localization.trust().get()).isFinite();
      assertThat(fixture.io.fused).hasSize(1);
      assertThat(localization.ingest(fixture.vision, 10.04)).isEmpty();
      assertThat(localization.poseAt(9.99)).isEmpty();
      assertThat(localization.poseAt(10.05)).isEmpty();
      localization.reset(new Pose2d(5, 4, Rotation2d.kZero), 10.05, fixture.vision);
      assertThat(localization.poseAt(10.04)).isEmpty();
      assertThat(localization.trust().get()).isInfinite();
      assertThat(localization.getPose().getX()).isEqualTo(5);
    }
  }

  @Test void missingEstimatorHistoryAndExpiredMeasurementsNeverReceiveFusionAcknowledgement() {
    try (var fixture = new VisionIntegrationTest.Fixture(true)) {
      var localization = new Localization(fixture.robot, 10.);
      fixture.frame("front", 1, 10.01);
      fixture.tick(10.04);
      assertThat(localization.ingest(fixture.vision, 10.04)).isEmpty();
      assertThat(localization.rejected()).isEqualTo(1);
      assertThat(fixture.io.fused).isEmpty();
      localization.updateOdometry(10.04);
      fixture.frame("front", 1, 10.05);
      fixture.tick(10.08);
      localization.updateOdometry(10.08);
      assertThat(localization.ingest(fixture.vision, 10.4)).isEmpty();
      assertThat(localization.rejected()).isEqualTo(2);
      assertThat(fixture.io.fused).isEmpty();
      assertThat(localization.trust().get()).isInfinite();
    }
  }
}
