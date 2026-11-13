package com.team581.spot;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import edu.wpi.first.apriltag.AprilTagFieldLayout;
import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.networktables.StringPublisher;
import edu.wpi.first.networktables.StringSubscriber;
import edu.wpi.first.networktables.StructSubscriber;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

/** NetworkTables client for Spot. */
public final class Spot implements AutoCloseable {
  private final NetworkTableInstance nt;
  private final StringPublisher config;
  private final StringPublisher fieldLayout;
  private final StructSubscriber<SpotStatus> status;
  private final StringSubscriber error;
  private final Map<String, SpotCamera> cameras = new HashMap<>();

  /**
   * Creates a client on the default NetworkTables instance.
   *
   * @param config Contents of the robot's {@code spot.toml}.
   * @param fieldLayout The field's AprilTag layout.
   */
  public Spot(String config, AprilTagFieldLayout fieldLayout) {
    this(NetworkTableInstance.getDefault(), config, fieldLayout);
  }

  /**
   * Creates a client.
   *
   * @param nt NetworkTables instance Spot connects to.
   * @param config Contents of the robot's {@code spot.toml}.
   * @param fieldLayout The field's AprilTag layout.
   */
  public Spot(NetworkTableInstance nt, String config, AprilTagFieldLayout fieldLayout) {
    this.nt = nt;
    this.config = nt.getStringTopic("/Spot/inputs/config").publish();
    this.config.set(config);
    this.fieldLayout = nt.getStringTopic("/Spot/inputs/fieldLayout").publish();
    try {
      this.fieldLayout.set(new ObjectMapper().writeValueAsString(fieldLayout));
    } catch (JsonProcessingException e) {
      // Spot reports the missing layout in its status and error.
    }
    status = nt.getStructTopic("/Spot/outputs/status", SpotStatus.struct).subscribe(null);
    error = nt.getStringTopic("/Spot/outputs/error").subscribe("");
  }

  /**
   * Returns the client for a camera.
   *
   * @param name The camera's name from the Spot config.
   */
  public SpotCamera camera(String name) {
    return cameras.computeIfAbsent(name, n -> new SpotCamera(nt, n));
  }

  /** Spot's latest status, or empty while Spot isn't connected. */
  public Optional<SpotStatus> status() {
    return status.exists() ? Optional.ofNullable(status.get()) : Optional.empty();
  }

  /** Details for Spot's current state, or an empty string when it's ready. */
  public String error() {
    return error.get();
  }

  @Override
  public void close() {
    config.close();
    fieldLayout.close();
    status.close();
    error.close();
    cameras.values().forEach(SpotCamera::close);
  }
}
