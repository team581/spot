// Move to shared folder after offseason
package frc.robot.vision;

import static com.google.common.base.Preconditions.checkArgument;
import static java.util.Comparator.comparingDouble;

import frc.robot.vision.results.VisionMeasurement;
import java.util.ArrayList;
import java.util.List;
import java.util.PriorityQueue;

/** Global capture-time ordering across robot loops and camera sources. */
public final class MeasurementQueue {
  private final PriorityQueue<VisionMeasurement> pending =
      new PriorityQueue<>(
          comparingDouble(VisionMeasurement::timestamp)
              .thenComparing(VisionMeasurement::source)
              .thenComparing(VisionMeasurement::frameId));
  private final double windowS;
  private final int capacity;
  private double lastReleased = Double.NEGATIVE_INFINITY;
  private double resetTime = Double.NEGATIVE_INFINITY;
  private long lateCount;
  private long overloadCount;

  public MeasurementQueue(double windowS, int capacity) {
    checkArgument(
        Double.isFinite(windowS) && windowS >= 0 && capacity >= 1,
        "valid reorder window and capacity required");
    this.windowS = windowS;
    this.capacity = capacity;
  }

  public boolean add(VisionMeasurement measurement) {
    if (measurement.timestamp() < lastReleased || measurement.timestamp() <= resetTime) {
      lateCount++;
      return false;
    }
    if (pending.size() >= capacity) {
      overloadCount++;
      return false;
    }
    pending.add(measurement);
    return true;
  }

  /** Reconnect invalidates unsent old frames but preserves the fused watermark. */
  public void clearPending() {
    pending.clear();
  }

  public long lateCount() {
    return lateCount;
  }

  public long overloadCount() {
    return overloadCount;
  }

  public List<VisionMeasurement> release(double now, int budget) {
    var result = new ArrayList<VisionMeasurement>();
    while (result.size() < budget
        && !pending.isEmpty()
        && pending.peek().timestamp() <= now - windowS) {
      var next = pending.remove();
      if (next.timestamp() < lastReleased || next.timestamp() <= resetTime) {
        lateCount++;
      } else {
        result.add(next);
        lastReleased = next.timestamp();
      }
    }
    return List.copyOf(result);
  }

  public void reset(double timestamp) {
    pending.clear();
    resetTime = timestamp;
    lastReleased = timestamp;
  }

  public int size() {
    return pending.size();
  }
}
