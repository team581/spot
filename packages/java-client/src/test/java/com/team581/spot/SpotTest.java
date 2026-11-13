package com.team581.spot;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.team581.spot.SpotEstimate.Candidate;
import edu.wpi.first.apriltag.AprilTagFieldLayout;
import edu.wpi.first.apriltag.AprilTagFields;
import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.math.geometry.Rotation3d;
import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.util.struct.Struct;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class SpotTest {
  private static final AprilTagFieldLayout EMPTY_FIELD = new AprilTagFieldLayout(List.of(), 16, 8);

  private NetworkTableInstance nt;

  /** Publishes a value the way Spot does: raw struct bytes stamped with the capture time. */
  private <T> void publishFromSpot(String topic, Struct<T> struct, T value, long timeUs) {
    var buffer = TestStructs.pack(struct, value);
    nt.getRawTopic(topic).publish(struct.getTypeString()).set(buffer.array(), timeUs);
  }

  @BeforeEach
  void setUp() {
    nt = NetworkTableInstance.create();
  }

  @AfterEach
  void tearDown() {
    nt.close();
  }

  @Test
  void publishesFieldLayoutInTheFormatSpotParses() throws Exception {
    var layout = AprilTagFieldLayout.loadField(AprilTagFields.kDefaultField);
    try (var spot = new Spot(nt, "[cameras.front]", layout);
        var config = nt.getStringTopic("/Spot/inputs/config").subscribe("");
        var fieldLayout = nt.getStringTopic("/Spot/inputs/fieldLayout").subscribe("")) {
      assertEquals("[cameras.front]", config.get());

      var json = new ObjectMapper().readTree(fieldLayout.get());
      var tag = json.get("tags").get(0);
      assertEquals(layout.getTags().get(0).ID, tag.get("ID").asInt());
      assertEquals(layout.getTags().get(0).pose.getX(), tag.at("/pose/translation/x").asDouble());
      assertTrue(tag.at("/pose/rotation/quaternion/W").isNumber());
      assertEquals(layout.getFieldLength(), json.at("/field/length").asDouble());
    }
  }

  @Test
  void callsBackWithEachEstimateAndItsCaptureTime() throws InterruptedException {
    try (var spot = new Spot(nt, "", EMPTY_FIELD)) {
      var estimates = new CopyOnWriteArrayList<TimestampedEstimate>();
      var received = new CountDownLatch(2);
      spot.camera("front")
          .onEstimate(estimate -> {
            estimates.add(estimate);
            received.countDown();
          });
      var topic = "/Spot/outputs/cameras/front/estimate";
      var first = new Candidate(new Pose3d(1, 2, 0, Rotation3d.kZero), 0.5);
      var second = new Candidate(new Pose3d(1.1, 2, 0, Rotation3d.kZero), 0.6);
      publishFromSpot(
          topic,
          SpotEstimate.struct,
          new SpotEstimate(first, Optional.empty(), new int[] {1, 12}, 3, 0.02),
          1_250_000);
      publishFromSpot(
          topic,
          SpotEstimate.struct,
          new SpotEstimate(second, Optional.empty(), new int[] {12}, 3, 0.02),
          1_500_000);

      assertTrue(received.await(1, TimeUnit.SECONDS));
      assertEquals(
          List.of(1.25, 1.5),
          estimates.stream().map(TimestampedEstimate::timestampSeconds).toList());
      var estimate = estimates.get(0).estimate();
      assertEquals(first, estimate.primary());
      assertTrue(estimate.alternate().isEmpty());
      assertArrayEquals(new int[] {1, 12}, estimate.tagIds());
    }
  }

  @Test
  void statusIsEmptyWhileSpotIsNotPublishing() {
    try (var spot = new Spot(nt, "", EMPTY_FIELD)) {
      assertEquals(Optional.empty(), spot.status());

      var status = new SpotStatus("2026.0.0", SpotStatus.State.READY, false);
      var publisher = nt.getRawTopic("/Spot/outputs/status").publish("struct:SpotStatus");
      publisher.set(TestStructs.pack(SpotStatus.struct, status).array());
      assertEquals(Optional.of(status), spot.status());

      // Spot's publishers go away when it disconnects.
      publisher.close();
      assertEquals(Optional.empty(), spot.status());
    }
  }
}
