package frc.robot.logging;

import com.fasterxml.jackson.databind.ObjectMapper;
import edu.wpi.first.util.datalog.RawLogEntry;
import edu.wpi.first.util.datalog.StringLogEntry;
import edu.wpi.first.util.datalog.DataLog;
import frc.robot.vision.SpotVisionIO;
import frc.robot.vision.VisionIO;
import frc.robot.vision.VisionProcessor;
import frc.robot.vision.results.VisionMeasurement;
import java.util.HashMap;
import java.util.Map;
import java.util.function.DoubleSupplier;

/** Records every delivered frame/decision directly, without dashboard update coalescing. */
public final class RecordingVisionIO implements VisionIO {
  private final VisionIO delegate;
  private final DoubleSupplier clock;
  private final DataLog log;
  private final StringLogEntry events;
  private final Map<String, RawLogEntry> raw = new HashMap<>();
  private final Map<String, LatencyWindow> received = new HashMap<>();
  private final Map<String, LatencyWindow> consumed = new HashMap<>();
  private final ObjectMapper json = new ObjectMapper();
  private Health health;
  private long frames;
  private long fused;
  private long loggingErrors;

  public RecordingVisionIO(VisionIO delegate, DoubleSupplier clock, DataLog log) {
    this.delegate = delegate;
    this.clock = clock;
    this.log = log;
    events = new StringLogEntry(log, "/Bench/Frames");
  }

  @Override public Inputs readInputs(double now, boolean enabled) {
    var inputs = delegate.readInputs(now, enabled);
    health = inputs.health();
    for (var sample : inputs.samples()) {
      frames++;
      raw.computeIfAbsent(sample.observation().getCameraName(), name ->
          new RawLogEntry(log, "/Bench/Raw/" + name,
              "proto:spot.vision.v2.Observation")).append(sample.observation().toByteArray());
    }
    return inputs;
  }

  @Override public void reportDecision(Sample sample, VisionProcessor.Decision decision) {
    delegate.reportDecision(sample, decision);
    double now = clock.getAsDouble();
    var observation = sample.observation();
    double ageMs = (now - sample.captureFpgaSeconds()) * 1000.;
    received.computeIfAbsent(observation.getCameraName(), name -> new LatencyWindow(4096)).add(ageMs);
    var event = new HashMap<String, Object>();
    event.put("camera", observation.getCameraName());
    event.put("sequence", observation.getSequence());
    event.put("capture_epoch", observation.getCaptureEpoch());
    event.put("service_session", observation.getServiceSession());
    event.put("connection_epoch", observation.getConnectionEpoch());
    event.put("sync_epoch", observation.getSyncEpoch());
    event.put("runtime_generation", observation.getRuntimeGeneration());
    event.put("capture_fpga_s", sample.captureFpgaSeconds());
    event.put("decision_fpga_s", now);
    event.put("decision_nt_s", edu.wpi.first.networktables.NetworkTablesJNI.now() / 1e6);
    event.put("age_ms", ageMs);
    event.put("decision", decision.reason().name());
    event.put("processing_ms", observation.getTiming().getTotalMs());
    event.put("timestamp_source", observation.getTimestampSource());
    event.put("timestamp_uncertainty_s", observation.getTimestampUncertaintyS());
    event.put("frame_id", decision.measurement().map(VisionMeasurement::frameId).orElse(""));
    append(event);
  }

  public void measurementConsumed(VisionMeasurement value, double now) {
    fused++;
    double ageMs = (now - value.timestamp()) * 1000.;
    consumed.computeIfAbsent(value.source(), name -> new LatencyWindow(4096)).add(ageMs);
    append(Map.of("camera", value.source(), "frame_id", value.frameId(), "decision", "BENCH_FUSED",
        "capture_fpga_s", value.timestamp(), "consume_fpga_s", now, "age_ms", ageMs));
  }

  public void publish() {
    BenchLog.log("Bench/FramesDelivered", frames);
    BenchLog.log("Bench/MeasurementsConsumed", fused);
    BenchLog.log("Bench/LoggingErrors", loggingErrors);
    if (delegate instanceof SpotVisionIO spot) BenchLog.log("Bench/MalformedPackets", spot.malformedCount());
    if (health != null) {
      BenchLog.log("Bench/TransportAvailable", health.available());
      BenchLog.log("Bench/TransportReason", health.reason());
      BenchLog.log("Bench/SyncState", health.service().getSyncState());
      BenchLog.log("Bench/SyncOffsetUs", health.service().getOffsetUs());
      BenchLog.log("Bench/SyncUpdateAgeS", health.service().getSyncUpdateAgeS());
    }
    received.forEach((name, stats) -> publish("Bench/" + name + "/DecisionAge", stats));
    consumed.forEach((name, stats) -> publish("Bench/" + name + "/ConsumptionAge", stats));
  }

  private static void publish(String path, LatencyWindow window) {
    var s = window.summary();
    BenchLog.log(path + "/Count", s.total());
    BenchLog.log(path + "/Invalid", s.invalid());
    BenchLog.log(path + "/WindowSize", s.windowSize());
    BenchLog.log(path + "/P50Ms", s.p50Ms());
    BenchLog.log(path + "/P95Ms", s.p95Ms());
    BenchLog.log(path + "/WindowMaxMs", s.windowMaxMs());
    BenchLog.log(path + "/LifetimeMaxMs", s.lifetimeMaxMs());
  }

  private void append(Map<String, Object> event) {
    try { events.append(json.writeValueAsString(event)); }
    catch (java.io.IOException exception) { loggingErrors++; }
  }

  @Override public void measurementFused(VisionMeasurement value) { delegate.measurementFused(value); }
  @Override public void publishDecisions(double now) { delegate.publishDecisions(now); }
  @Override public void reset(double now) { delegate.reset(now); }
  @Override public void setFusionEnabled(boolean enabled) { delegate.setFusionEnabled(enabled); }
  @Override public void setTagSelection(TagSelection selection) { delegate.setTagSelection(selection); }
  @Override public void close() { delegate.close(); }
}
