package frc.robot;

import static org.assertj.core.api.Assertions.assertThat;
import edu.wpi.first.hal.HAL;
import edu.wpi.first.wpilibj.smartdashboard.SmartDashboard;
import org.junit.jupiter.api.Test;

class RobotSmokeTest {
  @Test void robotStartsAndTicksWithoutAnyCanDevicesOrCameras() {
    HAL.initialize(500, 0);
    try (var robot = new Robot()) {
      robot.robotInit();
      robot.robotPeriodic();
      assertThat(SmartDashboard.getBoolean("Bench/ConfigLoaded", false)).isTrue();
      assertThat(SmartDashboard.getBoolean("Bench/EstimatorEnabled", true)).isFalse();
      assertThat(SmartDashboard.getString("Vision/Spot/Reason", ""))
          .isEqualTo("No measured camera configuration");
    }
  }
}
