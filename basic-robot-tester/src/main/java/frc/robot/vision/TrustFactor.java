// Move to shared folder after offseason
package frc.robot.vision;

import static java.util.Comparator.comparingDouble;

import frc.robot.vision.results.VisionMeasurement;
import java.util.ArrayDeque;
import java.util.List;

/** Capture-time evidence heuristic in metres, not covariance or probability. */
public final class TrustFactor {
  public record Policy(
      double trustworthyM,
      double lostM,
      double travelMPerM,
      double agingMPerS,
      double collisionM,
      double correlationS) {
    public static Policy provisional() {
      return new Policy(.254, 1., .05, .01, 2., .02);
    }
  }

  private record Penalty(double time, double value) {}

  private final Policy policy = Policy.provisional();
  private final ArrayDeque<Penalty> history = new ArrayDeque<>();
  private double score = Double.POSITIVE_INFINITY;
  private double evidenceTimestamp = Double.NEGATIVE_INFINITY;
  private double groupStart = Double.NEGATIVE_INFINITY;
  private double groupWorst;
  private double groupPenalty;
  private double penalty;
  private double time;
  private boolean collisionActive;

  public double evidenceAge(double now) {
    return now - evidenceTimestamp;
  }

  public double get() {
    return score;
  }

  /** Caller supplies only measurements actually submitted to the estimator. */
  public void ingest(List<VisionMeasurement> fused) {
    for (var value :
        fused.stream().sorted(comparingDouble(VisionMeasurement::timestamp)).toList()) {
      if (value.timestamp() < evidenceTimestamp) continue;
      double evidence = value.innovationM() + Math.hypot(value.stdX(), value.stdY());
      if (!Double.isFinite(evidence) || value.innovationM() < 0) continue;
      if (value.timestamp() - groupStart > policy.correlationS()) {
        groupStart = value.timestamp();
        groupWorst = evidence;
        groupPenalty = penaltyAt(groupStart);
      } else {
        groupWorst = Math.max(groupWorst, evidence);
      }
      score = groupWorst + Math.max(0., penalty - groupPenalty);
      evidenceTimestamp = value.timestamp();
    }
  }

  public boolean isLost() {
    return score >= policy.lostM();
  }

  public boolean isTrustworthy() {
    return score <= policy.trustworthyM();
  }

  public void reset(double now, boolean explicitlySeeded) {
    if (!Double.isFinite(now)) throw new IllegalArgumentException("finite reset time required");
    score = explicitlySeeded ? policy.trustworthyM() : Double.POSITIVE_INFINITY;
    evidenceTimestamp = groupStart = Double.NEGATIVE_INFINITY;
    collisionActive = false;
    penalty = 0.;
    time = now;
    history.clear();
    history.addLast(new Penalty(now, 0.));
  }

  public void updateOdometry(double distanceM, double elapsedS, boolean collision) {
    if (!Double.isFinite(distanceM) || !Double.isFinite(elapsedS) || distanceM < 0 || elapsedS < 0)
      throw new IllegalArgumentException("nonnegative finite metres and seconds required");
    double delta = distanceM * policy.travelMPerM() + elapsedS * policy.agingMPerS();
    if (collision && !collisionActive) delta += policy.collisionM();
    collisionActive = collision;
    score += delta;
    penalty += delta;
    time += elapsedS;
    history.addLast(new Penalty(time, penalty));
    while (history.size() > 256) history.removeFirst();
  }

  private double penaltyAt(double timestamp) {
    if (history.isEmpty()) return penalty;
    Penalty previous = history.getFirst();
    for (var next : history) {
      if (next.time() >= timestamp) {
        double span = next.time() - previous.time();
        double fraction = span <= 0 ? 0 : Math.max(0, (timestamp - previous.time()) / span);
        return previous.value() + fraction * (next.value() - previous.value());
      }
      previous = next;
    }
    return penalty;
  }
}
