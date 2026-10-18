package frc.robot.logging;

import java.util.Arrays;

/** Bounded rolling percentiles; lifetime sample and invalid counts are separate. */
public final class LatencyWindow {
  public record Summary(long total, long invalid, int windowSize, double p50Ms, double p95Ms,
      double windowMaxMs, double lifetimeMaxMs) {}
  private final double[] values;
  private int size;
  private int next;
  private long total;
  private long invalid;
  private double maximum = Double.NaN;

  public LatencyWindow(int capacity) {
    if (capacity < 1) throw new IllegalArgumentException("positive capacity required");
    values = new double[capacity];
  }

  public void add(double milliseconds) {
    if (!Double.isFinite(milliseconds) || milliseconds < 0) { invalid++; return; }
    values[next] = milliseconds;
    next = (next + 1) % values.length;
    size = Math.min(size + 1, values.length);
    total++;
    maximum = Double.isNaN(maximum) ? milliseconds : Math.max(maximum, milliseconds);
  }

  public Summary summary() {
    double[] sorted = Arrays.copyOf(values, size);
    Arrays.sort(sorted);
    return new Summary(total, invalid, size, percentile(sorted, .5), percentile(sorted, .95),
        size == 0 ? Double.NaN : sorted[size - 1], maximum);
  }

  private static double percentile(double[] sorted, double fraction) {
    return sorted.length == 0 ? Double.NaN : sorted[(int) Math.ceil(sorted.length * fraction) - 1];
  }
}
