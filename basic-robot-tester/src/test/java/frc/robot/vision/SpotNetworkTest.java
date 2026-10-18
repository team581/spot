package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;

import edu.wpi.first.hal.HAL;
import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.networktables.NetworkTablesJNI;
import edu.wpi.first.networktables.PubSubOption;
import frc.robot.vision.generated.SpotProtos;
import java.net.ServerSocket;
import java.util.ArrayList;
import org.junit.jupiter.api.Test;

/** Actual local NT4 client/server handoff, beyond the scripted pipeline tests. */
class SpotNetworkTest {
  private static double now() { return NetworkTablesJNI.now() / 1e6; }

  @Test void queuedRemoteObservationsRetainCaptureTimesAndMalformedBytesAreCounted() throws Exception {
    HAL.initialize(500, 0);
    int port;
    try (var socket = new ServerSocket(0)) { port = socket.getLocalPort(); }
    try (var fixture = new VisionIntegrationTest.Fixture(false);
        var server = NetworkTableInstance.create(); var client = NetworkTableInstance.create()) {
      server.startServer("", "127.0.0.1", 0, port);
      client.setServer("127.0.0.1", port);
      client.startClient4("bench-contract-test");
      long deadline = System.nanoTime() + 5_000_000_000L;
      while ((!client.isConnected() || client.getServerTimeOffset().isEmpty())
          && System.nanoTime() < deadline) Thread.sleep(10);
      assertThat(client.isConnected()).isTrue();
      assertThat(client.getServerTimeOffset()).isPresent();
      try (var io = new SpotVisionIO(server, fixture.profile, "robot");
          var ack = client.getRawTopic("/Spot/v2/config/ack")
              .publish("proto:spot.vision.v2.Acknowledgement", PubSubOption.sendAll(true));
          var health = client.getRawTopic("/Spot/v2/health")
              .publish("proto:spot.vision.v2.Health", PubSubOption.sendAll(true));
          var frames = client.getRawTopic("/Spot/v2/front/observations")
              .publish("proto:spot.vision.v2.Observation", PubSubOption.sendAll(true),
                  PubSubOption.keepDuplicates(true))) {
        io.setTagSelection(fixture.io.selection);
        io.readInputs(now(), false);
        ack.set(fixture.io.ack.toByteArray());
        health.set(SpotProtos.Health.newBuilder().setSchemaVersion(2).setSequence(1)
            .setServiceSession("service").setRuntimeGeneration("runtime")
            .setConnectionEpoch(1).setSyncEpoch(1).setSyncState("Synchronized").build().toByteArray());
        client.flush();
        deadline = System.nanoTime() + 2_000_000_000L;
        VisionIO.Inputs inputs;
        do {
          Thread.sleep(5);
          inputs = io.readInputs(now(), false);
        } while (!inputs.health().available() && System.nanoTime() < deadline);
        assertThat(inputs.health().available()).as(inputs.health().reason()).isTrue();
        fixture.frame("front", 1, 10.01);
        fixture.frame("front", 1, 10.02);
        long captureUs = NetworkTablesJNI.now() - 30_000;
        frames.set(fixture.io.samples.get(0).observation().toByteArray(), captureUs);
        frames.set(fixture.io.samples.get(1).observation().toByteArray(), captureUs + 1_000);
        frames.set(new byte[] {(byte) 0xff}, captureUs + 2_000);
        client.flush();
        var received = new ArrayList<VisionIO.Sample>();
        deadline = System.nanoTime() + 300_000_000L;
        do {
          Thread.sleep(5);
          received.addAll(io.readInputs(now(), false).samples());
        } while ((received.size() < 2 || io.malformedCount() == 0) && System.nanoTime() < deadline);
        assertThat(received).hasSize(2);
        assertThat(received.get(1).observation().getSequence())
            .isGreaterThan(received.get(0).observation().getSequence());
        assertThat(received.get(1).captureFpgaSeconds() - received.get(0).captureFpgaSeconds())
            .isCloseTo(.001, org.assertj.core.data.Offset.offset(1e-6));
        assertThat(now() - received.get(0).captureFpgaSeconds()).isBetween(0., .5);
        assertThat(io.malformedCount()).isEqualTo(1);
      }
    }
  }
}
