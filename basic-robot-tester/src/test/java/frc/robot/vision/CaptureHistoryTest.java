package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.data.Offset.offset;

import edu.wpi.first.math.geometry.Pose2d;
import java.util.Optional;
import org.junit.jupiter.api.Test;

final class CaptureHistoryTest {
  private static VisionProcessor.CaptureState state(double speed) {
    return new VisionProcessor.CaptureState(Pose2d.kZero, speed, speed * 2, speed * .1, 0, 0);
  }

  @Test
  void interpolationHasExplicitEndpointsAndRejectsMissingOrInvalidHistory() {
    var history = new CaptureHistory(time -> Optional.of(Pose2d.kZero));
    history.add(10., state(1));
    history.add(10.1, state(3));
    history.add(10.05, state(99));
    assertThat(history.at(10.).orElseThrow().speedMps()).isEqualTo(1.);
    assertThat(history.at(10.1).orElseThrow().speedMps()).isEqualTo(3.);
    assertThat(history.at(10.05).orElseThrow().speedMps()).isCloseTo(2., offset(1e-10));
    assertThat(history.at(9.99)).isEmpty();
    assertThat(history.at(10.11)).isEmpty();
    history.add(10.2, state(Double.NaN));
    assertThat(history.at(10.2)).isEmpty();
    history.reset();
    assertThat(history.at(10.05)).isEmpty();
    var missing = new CaptureHistory(time -> Optional.empty());
    missing.add(10., state(0));
    assertThat(missing.at(10.)).isEmpty();
  }

  @Test
  void sampleCapacityAndTimeBoundsRetireOldEvidence() {
    var history = new CaptureHistory(time -> Optional.of(Pose2d.kZero));
    for (int i = 0; i < 130; i++) history.add(10. + i * .001, state(0));
    assertThat(history.at(10.)).isEmpty();
    assertThat(history.at(10.129)).isPresent();
    history.add(13., state(0));
    assertThat(history.at(10.129)).isEmpty();
  }
}
