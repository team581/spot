package frc.robot.logging;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;

class LatencyWindowTest {
  @Test void percentilesAreBoundedButLifetimeMaximumSurvives() {
    var window = new LatencyWindow(3);
    window.add(100);
    window.add(10);
    window.add(20);
    window.add(30);
    window.add(-1);
    window.add(Double.NaN);
    var s = window.summary();
    assertThat(s.total()).isEqualTo(4);
    assertThat(s.invalid()).isEqualTo(2);
    assertThat(s.windowSize()).isEqualTo(3);
    assertThat(s.p50Ms()).isEqualTo(20);
    assertThat(s.p95Ms()).isEqualTo(30);
    assertThat(s.windowMaxMs()).isEqualTo(30);
    assertThat(s.lifetimeMaxMs()).isEqualTo(100);
  }
}
