package frc.robot.logging;

import edu.wpi.first.wpilibj.smartdashboard.SmartDashboard;

/** Dashboard entries are also recorded by DataLogManager's NetworkTables logging. */
public final class BenchLog {
  public static void log(String key, boolean value) { SmartDashboard.putBoolean(key, value); }
  public static void log(String key, double value) { SmartDashboard.putNumber(key, value); }
  public static void log(String key, String value) { SmartDashboard.putString(key, value); }
  public static void logFault(String fault) { log("Faults/" + fault, true); }
  public static void clearFault(String fault) { log("Faults/" + fault, false); }
  private BenchLog() {}
}
