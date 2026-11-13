package com.team581.spot;

import edu.wpi.first.networktables.NetworkTableEvent;
import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.networktables.PubSubOption;
import edu.wpi.first.networktables.StructSubscriber;
import edu.wpi.first.util.struct.StructBuffer;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.Optional;
import java.util.function.Consumer;

/** One camera's estimates and status. Get one from {@link Spot#camera(String)}. */
public final class SpotCamera implements AutoCloseable {
  private final NetworkTableInstance nt;
  private final String name;
  private final StructSubscriber<SpotEstimate> estimates;
  private final StructSubscriber<SpotCameraStatus> status;
  private final List<Integer> listeners = new ArrayList<>();

  SpotCamera(NetworkTableInstance nt, String name) {
    this.nt = nt;
    this.name = name;
    var prefix = "/Spot/outputs/cameras/" + name + "/";
    estimates =
        nt.getStructTopic(prefix + "estimate", SpotEstimate.struct)
            .subscribe(null, PubSubOption.sendAll(true), PubSubOption.keepDuplicates(true));
    status = nt.getStructTopic(prefix + "status", SpotCameraStatus.struct).subscribe(null);
  }

  /** The camera's name from the Spot config. */
  public String name() {
    return name;
  }

  /**
   * Runs {@code callback} for each estimate as it arrives. The callback runs on the NetworkTables
   * listener thread, so it must be thread-safe.
   */
  public void onEstimate(Consumer<TimestampedEstimate> callback) {
    // Only the listener thread uses this buffer.
    var buffer = StructBuffer.create(SpotEstimate.struct);
    listeners.add(
        nt.addListener(
            estimates,
            EnumSet.of(NetworkTableEvent.Kind.kValueAll),
            event -> {
              var value = event.valueData.value;
              SpotEstimate estimate;
              try {
                estimate = buffer.read(value.getRaw());
              } catch (RuntimeException e) {
                // Skip values from an incompatible Spot version.
                return;
              }
              callback.accept(new TimestampedEstimate(value.getTime() / 1e6, estimate));
            }));
  }

  /** The camera's latest status, or empty while Spot isn't publishing it. */
  public Optional<SpotCameraStatus> status() {
    return status.exists() ? Optional.ofNullable(status.get()) : Optional.empty();
  }

  @Override
  public void close() {
    listeners.forEach(nt::removeListener);
    estimates.close();
    status.close();
  }
}
