// Move to shared folder after offseason
package frc.robot.vision;

import edu.wpi.first.math.geometry.Pose2d;
import java.util.ArrayDeque;
import java.util.Optional;
import java.util.function.DoubleFunction;

/** Bounded capture-time motion/tilt history with explicit bounds, never clamping. */
public final class CaptureHistory implements VisionProcessor.History {
  private record Entry(double timestamp, VisionProcessor.CaptureState state) {}

  private static double interpolate(double a, double b, double fraction) {
    return a + (b - a) * fraction;
  }

  private final ArrayDeque<Entry> samples = new ArrayDeque<>();

  private final DoubleFunction<Optional<Pose2d>> poseAt;

  public CaptureHistory(DoubleFunction<Optional<Pose2d>> poseAt) {
    this.poseAt = poseAt;
  }

  public void add(double timestamp, VisionProcessor.CaptureState state) {
    if (!Double.isFinite(timestamp)
        || state.pose() == null
        || !Double.isFinite(state.pose().getX())
        || !Double.isFinite(state.pose().getY())
        || !Double.isFinite(state.pose().getRotation().getRadians())
        || !Double.isFinite(state.speedMps())
        || state.speedMps() < 0
        || !Double.isFinite(state.angularRateRadPerS())
        || !Double.isFinite(state.rollRad())
        || !Double.isFinite(state.pitchRad())
        || !Double.isFinite(state.zM())
        || (!samples.isEmpty() && timestamp <= samples.getLast().timestamp())) {
      return;
    }
    samples.addLast(new Entry(timestamp, state));
    while (samples.size() > 128 || timestamp - samples.getFirst().timestamp() > 2.) {
      samples.removeFirst();
    }
  }

  @Override
  public Optional<VisionProcessor.CaptureState> at(double timestamp) {
    if (!Double.isFinite(timestamp)
        || samples.isEmpty()
        || timestamp < samples.getFirst().timestamp()
        || timestamp > samples.getLast().timestamp()) {
      return Optional.empty();
    }
    var pose = poseAt.apply(timestamp);
    if (pose.isEmpty()) {
      return Optional.empty();
    }
    Entry previous = samples.getFirst();
    for (var sample : samples) {
      if (sample.timestamp() >= timestamp) {
        double span = sample.timestamp() - previous.timestamp();
        double fraction = span == 0 ? 0 : (timestamp - previous.timestamp()) / span;
        var a = previous.state();
        var b = sample.state();
        return Optional.of(
            new VisionProcessor.CaptureState(
                pose.orElseThrow(),
                interpolate(a.speedMps(), b.speedMps(), fraction),
                interpolate(a.angularRateRadPerS(), b.angularRateRadPerS(), fraction),
                interpolate(a.rollRad(), b.rollRad(), fraction),
                interpolate(a.pitchRad(), b.pitchRad(), fraction),
                interpolate(a.zM(), b.zM(), fraction)));
      }
      previous = sample;
    }
    return Optional.empty();
  }

  public void reset() {
    samples.clear();
  }
}
