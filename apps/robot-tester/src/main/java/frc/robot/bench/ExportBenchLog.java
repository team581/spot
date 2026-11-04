package frc.robot.bench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import edu.wpi.first.util.datalog.DataLogReader;
import edu.wpi.first.util.datalog.DataLogRecord.StartRecordData;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/** Desktop-only export using WPILib's reader; no robot connection or native runtime needed. */
public final class ExportBenchLog {
  public static void main(String... args) throws IOException {
    if (args.length != 2) throw new IllegalArgumentException("input.wpilog output.jsonl required");
    export(Path.of(args[0]), Path.of(args[1]));
  }

  public static void export(Path input, Path output) throws IOException {
    var reader = new DataLogReader(input.toString());
    if (!reader.isValid()) throw new IOException("Invalid WPILOG: " + input);
    var json = new ObjectMapper();
    Map<Integer, StartRecordData> entries = new HashMap<>();
    try (var writer = Files.newBufferedWriter(output)) {
      for (var record : reader) {
        if (record.isStart()) {
          var start = record.getStartData();
          entries.put(start.entry, start);
        } else if (record.isFinish()) {
          entries.remove(record.getFinishEntry());
        } else if (!record.isControl()) {
          var entry = entries.get(record.getEntry());
          if (entry == null) continue;
          ObjectNode event;
          if (entry.name.equals("/Bench/Frames") && entry.type.equals("string")) {
            var parsed = json.readTree(record.getString());
            if (!(parsed instanceof ObjectNode object)) throw new IOException("Invalid frame record");
            event = object;
            event.put("_kind", "frame");
          } else if (entry.name.startsWith("/Bench/Telemetry/")) {
            event = json.createObjectNode();
            event.put("_kind", "telemetry");
            event.put("key", entry.name.substring("/Bench/Telemetry/".length()));
            switch (entry.type) {
              case "double" -> event.put("value", record.getDouble());
              case "boolean" -> event.put("value", record.getBoolean());
              case "string" -> event.put("value", record.getString());
              default -> { continue; }
            }
          } else continue;
          event.put("_log_fpga_s", record.getTimestamp() / 1e6);
          writer.write(json.writeValueAsString(event));
          writer.newLine();
        }
      }
    }
  }

  private ExportBenchLog() {}
}
