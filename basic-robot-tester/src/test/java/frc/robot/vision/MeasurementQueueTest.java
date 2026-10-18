package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;

import com.google.common.collect.ImmutableList;
import edu.wpi.first.math.geometry.Pose2d;
import frc.robot.vision.results.VisionMeasurement;
import org.junit.jupiter.api.Test;

final class MeasurementQueueTest {
  private static VisionMeasurement value(String source, String frame, double timestamp) {
    return new VisionMeasurement(
        source, frame, Pose2d.kZero, timestamp, .1, .1, 1e6, ImmutableList.of(1), 0, 0);
  }

  @Test
  void capacityReleaseBudgetAndStableTiesRemainBounded() {
    var queue = new MeasurementQueue(.02, 3);
    queue.add(value("right", "b", 10.));
    queue.add(value("left", "b", 10.));
    queue.add(value("left", "a", 10.));
    assertThat(queue.add(value("back", "overflow", 10.))).isFalse();
    assertThat(queue.overloadCount()).isEqualTo(1);
    assertThat(queue.release(10.03, 2).stream().map(VisionMeasurement::frameId))
        .containsExactly("a", "b");
    assertThat(queue.size()).isEqualTo(1);
    assertThat(queue.release(10.03, 2).stream().map(VisionMeasurement::source))
        .containsExactly("right");
    queue.clearPending();
    assertThat(queue.add(value("back", "late", 9.99))).isFalse();
    assertThat(queue.lateCount()).isEqualTo(1);
  }
}
