package frc.robot.bench;

import static org.assertj.core.api.Assertions.assertThat;
import com.fasterxml.jackson.databind.ObjectMapper;
import edu.wpi.first.hal.HAL;
import edu.wpi.first.util.datalog.DataLogBackgroundWriter;
import edu.wpi.first.util.datalog.StringLogEntry;
import frc.robot.logging.BenchLog;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

final class ExportBenchLogTest {
  @TempDir Path directory;

  @Test void independentWriterExportsFramesAndTypedTelemetryWithoutDriverStation() throws Exception {
    HAL.initialize(500, 0);
    Path log = directory.resolve("bench-test.wpilog");
    try (var writer = new DataLogBackgroundWriter(directory.toString(), log.getFileName().toString(), .01)) {
      BenchLog.setSink(writer);
      new StringLogEntry(writer, "/Bench/Frames").append(
          "{\"camera\":\"front\",\"decision\":\"NO_TAGS\",\"capture_fpga_s\":10,\"decision_fpga_s\":10.02}");
      BenchLog.log("Bench/LoopWorkMs", 2.5);
      BenchLog.log("Bench/ConfigLoaded", true);
      BenchLog.log("Bench/RobotSession", "test-session");
      BenchLog.setSink(null);
      writer.flush();
    }
    Path exported = directory.resolve("frames.jsonl");
    ExportBenchLog.export(log, exported);
    var rows = Files.readAllLines(exported);
    assertThat(rows).hasSize(4);
    var json = new ObjectMapper();
    var frame = json.readTree(rows.get(0));
    assertThat(frame.get("_kind").asText()).isEqualTo("frame");
    assertThat(frame.get("decision").asText()).isEqualTo("NO_TAGS");
    assertThat(frame.has("_log_fpga_s")).isTrue();
    assertThat(json.readTree(rows.get(1)).get("value").asDouble()).isEqualTo(2.5);
    assertThat(json.readTree(rows.get(2)).get("value").asBoolean()).isTrue();
    assertThat(json.readTree(rows.get(3)).get("value").asText()).isEqualTo("test-session");
  }
}
