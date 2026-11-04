package frc.robot;

import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.util.datalog.DataLogBackgroundWriter;
import edu.wpi.first.wpilibj.DataLogManager;
import edu.wpi.first.wpilibj.DriverStation;
import edu.wpi.first.wpilibj.TimedRobot;
import edu.wpi.first.wpilibj.Timer;
import edu.wpi.first.wpilibj.smartdashboard.Field2d;
import edu.wpi.first.wpilibj.smartdashboard.SmartDashboard;
import frc.robot.localization.Localization;
import frc.robot.logging.BenchLog;
import frc.robot.logging.RecordingVisionIO;
import frc.robot.vision.SpotVisionIO;
import frc.robot.vision.Vision;
import java.util.UUID;

/** Bare roboRIO bench harness. No motor controllers, CAN devices, gyro or drivetrain required. */
public final class Robot extends TimedRobot {
  private final Field2d field = new Field2d();
  private BenchConfig config;
  private Localization localization;
  private Vision vision;
  private RecordingVisionIO io;
  private DataLogBackgroundWriter benchLog;
  private double lastPublish = Double.NEGATIVE_INFINITY;
  private double previousLoop = Double.NaN;

  @Override
  public void close() {
    if (vision != null) vision.close();
    BenchLog.setSink(null);
    if (benchLog != null) {
      benchLog.flush();
      benchLog.close();
    }
    field.close();
    super.close();
  }

  @Override
  public void robotInit() {
    DataLogManager.start();
    String session = UUID.randomUUID().toString();
    // DataLogManager pauses without DS packets; this writer has an independent lifetime.
    benchLog =
        new DataLogBackgroundWriter(
            DataLogManager.getLogDir(), "bench-" + session + ".wpilog", .25);
    BenchLog.setSink(benchLog);
    BenchLog.log("Bench/RobotSession", session);
    BenchLog.log("Bench/LogDirectory", DataLogManager.getLogDir());
    DataLogManager.logNetworkTables(true);
    DriverStation.startDataLog(DataLogManager.getLog());
    SmartDashboard.putData("Bench/Field", field);
    SmartDashboard.putBoolean("Bench/UseVision", true);
    SmartDashboard.putBoolean("Bench/HubTags", false);
    SmartDashboard.putBoolean("Bench/ResetPose", false);
    try {
      config = BenchConfig.create();
      localization = new Localization(config.stationaryPose(), Timer.getFPGATimestamp());
      io =
          new RecordingVisionIO(
              new SpotVisionIO(NetworkTableInstance.getDefault(), config.profile(), session),
              Timer::getFPGATimestamp,
              benchLog);
      vision =
          new Vision(
              io,
              config.profile(),
              config.mounts(),
              localization,
              Timer::getFPGATimestamp,
              DriverStation::isEnabled,
              () -> SmartDashboard.getBoolean("Bench/UseVision", true),
              DriverStation::getAlliance);
      BenchLog.log("Bench/ConfigLoaded", true);
      BenchLog.log("Bench/EstimatorEnabled", config.profile().fusionEnabled());
      BenchLog.log("Bench/ProfileHash", frc.robot.vision.SpotProtocol.hash(config.profile()));
      DataLogManager.log("Bench configuration loaded: " + config.profile().robotId());
    } catch (Exception | ExceptionInInitializerError exception) {
      Throwable failure =
          exception instanceof ExceptionInInitializerError && exception.getCause() != null
              ? exception.getCause()
              : exception;
      BenchLog.log("Bench/ConfigLoaded", false);
      BenchLog.log("Bench/ConfigError", failure.toString());
      DriverStation.reportError("Bench configuration failed: " + failure, failure.getStackTrace());
    }
  }

  @Override
  public void robotPeriodic() {
    double start = Timer.getFPGATimestamp();
    if (Double.isFinite(previousLoop))
      BenchLog.log("Bench/LoopIntervalMs", (start - previousLoop) * 1000);
    previousLoop = start;
    if (vision == null) return;
    if (isDisabled() && SmartDashboard.getBoolean("Bench/ResetPose", false)) {
      localization.reset(config.stationaryPose(), start, vision);
      SmartDashboard.putBoolean("Bench/ResetPose", false);
    }
    if (SmartDashboard.getBoolean("Bench/HubTags", false)) vision.hubTagsRequest();
    else vision.tagsRequest();
    localization.updateOdometry(start);
    vision.collectInputs();
    // This loop runs while disabled too, allowing testing without enabling outputs.
    localization.ingest(
        vision,
        Timer.getFPGATimestamp(),
        value -> io.measurementConsumed(value, Timer.getFPGATimestamp()));
    vision.robotPeriodic();
    if (start - lastPublish >= .2) {
      lastPublish = start;
      io.publish();
      BenchLog.log(
          "Bench/NtFpgaDeltaUs",
          edu.wpi.first.networktables.NetworkTablesJNI.now() - Timer.getFPGATimestamp() * 1e6);
      field.setRobotPose(localization.getPose());
      BenchLog.log("Bench/TrustM", localization.trust().get());
      BenchLog.log("Bench/EvidenceAgeS", localization.trust().evidenceAge(start));
      BenchLog.log("Bench/IngestionRejected", localization.rejected());
      BenchLog.log("Bench/AllRequiredHealthy", vision.getStatus().allRequiredHealthy());
    }
    BenchLog.log("Bench/LoopWorkMs", (Timer.getFPGATimestamp() - start) * 1000);
  }
}
