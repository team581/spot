package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.data.Offset.offset;

import com.google.common.collect.ImmutableList;
import edu.wpi.first.math.geometry.Pose2d;
import frc.robot.vision.results.VisionMeasurement;
import org.junit.jupiter.api.Test;

final class TrustFactorTest {
  private static VisionMeasurement measurement(double time, double innovation) {
    return new VisionMeasurement(
        "front",
        "frame" + time,
        Pose2d.kZero,
        time,
        .1,
        .1,
        1e6,
        ImmutableList.of(1),
        innovation,
        innovation / Math.hypot(.1, .1));
  }

  @Test
  void correlatedEvidenceHasIdenticalOutcomeAcrossBatchesAtCommonObservationTime() {
    var batch = new TrustFactor();
    var split = new TrustFactor();
    batch.reset(10., false);
    split.reset(10., false);
    var strong = measurement(10.01, .01);
    var weak = measurement(10.02, .2);
    batch.updateOdometry(.1, .04, false);
    batch.ingest(ImmutableList.of(strong, weak));
    split.updateOdometry(.05, .02, false);
    split.ingest(ImmutableList.of(strong));
    split.updateOdometry(.05, .02, false);
    split.ingest(ImmutableList.of(weak));
    assertThat(split.get()).isCloseTo(batch.get(), offset(1e-12));
    assertThat(batch.get()).isCloseTo(.2 + Math.hypot(.1, .1) + .00405, offset(1e-12));
    assertThat(split.isTrustworthy()).isFalse();
    double before = split.get();
    split.ingest(ImmutableList.of(strong));
    assertThat(split.get()).isEqualTo(before); // stale evidence cannot improve confidence
  }

  @Test
  void seedingIsNotCameraEvidenceAndOdometryUsesPhysicalDistance() {
    var trust = new TrustFactor();
    trust.reset(10., false);
    assertThat(trust.isTrustworthy()).isFalse();
    trust.reset(10., true);
    assertThat(trust.isTrustworthy()).isTrue();
    assertThat(trust.evidenceAge(10.)).isInfinite();
    trust.updateOdometry(0., 1., false);
    assertThat(trust.get()).isCloseTo(.264, offset(1e-12));
    trust.updateOdometry(2., 0., true);
    trust.updateOdometry(0., 0., true);
    assertThat(trust.get()).isCloseTo(2.364, offset(1e-12));
    trust.updateOdometry(0., 0., false);
    trust.updateOdometry(0., 0., true);
    assertThat(trust.get()).isCloseTo(4.364, offset(1e-12));
    assertThatThrownBy(() -> trust.updateOdometry(-1., 0., false))
        .isInstanceOf(IllegalArgumentException.class);
  }
}
