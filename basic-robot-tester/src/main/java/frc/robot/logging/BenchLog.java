package frc.robot.logging;

import edu.wpi.first.wpilibj.smartdashboard.SmartDashboard;
import edu.wpi.first.util.datalog.BooleanLogEntry;
import edu.wpi.first.util.datalog.DataLog;
import edu.wpi.first.util.datalog.DoubleLogEntry;
import edu.wpi.first.util.datalog.StringLogEntry;
import java.util.HashMap;
import java.util.Map;

/** Dashboard plus an independent bench log that continues without Driver Station packets. */
public final class BenchLog {
  private static DataLog sink;
  private static final Map<String, BooleanLogEntry> booleans = new HashMap<>();
  private static final Map<String, DoubleLogEntry> numbers = new HashMap<>();
  private static final Map<String, StringLogEntry> strings = new HashMap<>();

  public static void setSink(DataLog log) {
    sink = log;
    booleans.clear();
    numbers.clear();
    strings.clear();
  }

  public static void log(String key, boolean value) {
    SmartDashboard.putBoolean(key, value);
    if (sink != null) booleans.computeIfAbsent(key,
        k -> new BooleanLogEntry(sink, "/Bench/Telemetry/" + k)).append(value);
  }
  public static void log(String key, double value) {
    SmartDashboard.putNumber(key, value);
    if (sink != null) numbers.computeIfAbsent(key,
        k -> new DoubleLogEntry(sink, "/Bench/Telemetry/" + k)).append(value);
  }
  public static void log(String key, String value) {
    SmartDashboard.putString(key, value);
    if (sink != null) strings.computeIfAbsent(key,
        k -> new StringLogEntry(sink, "/Bench/Telemetry/" + k)).append(value);
  }
  public static void logFault(String fault) { log("Faults/" + fault, true); }
  public static void clearFault(String fault) { log("Faults/" + fault, false); }
  private BenchLog() {}
}
