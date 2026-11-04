package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;

import edu.wpi.first.hal.HAL;
import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.networktables.NetworkTablesJNI;
import edu.wpi.first.networktables.PubSubOption;
import frc.robot.vision.data.*;
import frc.robot.vision.structs.Heartbeat;
import java.net.ServerSocket;
import java.util.ArrayList;
import org.junit.jupiter.api.Test;

/** Actual local NT4 client/server handoff, beyond the scripted pipeline tests. */
class SpotNetworkTest {
  private static double now() {
    return NetworkTablesJNI.now() / 1e6;
  }

  @Test
  void freshManifestRepeatsWithinAReconnectRecoveryWindow() throws Exception {
    HAL.initialize(500, 0);
    int port;
    try (var socket = new ServerSocket(0)) {
      port = socket.getLocalPort();
    }
    try (var fixture = new VisionIntegrationTest.Fixture(false);
        var server = NetworkTableInstance.create();
        var client = NetworkTableInstance.create()) {
      server.startServer("", "127.0.0.1", 0, port);
      client.setServer("127.0.0.1", port);
      client.startClient4("manifest-recovery-test");
      long deadline = System.nanoTime() + 5_000_000_000L;
      while (!client.isConnected() && System.nanoTime() < deadline) Thread.sleep(10);
      assertThat(client.isConnected()).isTrue();
      try (var io = new SpotVisionIO(server, fixture.profile, "robot");
          var profiles =
              client
                  .getStringTopic(SpotVisionIO.ROOT + "/robot/manifest")
                  .subscribe(
                      "",
                      PubSubOption.keepDuplicates(true),
                      PubSubOption.sendAll(true),
                      PubSubOption.periodic(.005),
                      PubSubOption.pollStorage(16))) {
        var received = new ArrayList<edu.wpi.first.networktables.TimestampedString>();
        long start = System.nanoTime();
        while (System.nanoTime() - start < 600_000_000L) {
          io.readInputs(now(), false);
          server.flush();
          Thread.sleep(10);
          received.addAll(java.util.Arrays.asList(profiles.readQueue()));
        }
        assertThat(received.size()).isGreaterThanOrEqualTo(3);
        assertThat(received.get(received.size() - 1).timestamp)
            .isGreaterThan(received.get(0).timestamp);
        for (var sample : received)
          assertThat(sample.value).isEqualTo(io.manifest().manifestHash());
      }
    }
  }

  @Test
  void queuedRemoteObservationsRetainCaptureTimesAndMalformedBytesAreCounted() throws Exception {
    HAL.initialize(500, 0);
    int port;
    try (var socket = new ServerSocket(0)) {
      port = socket.getLocalPort();
    }
    try (var fixture = new VisionIntegrationTest.Fixture(false);
        var server = NetworkTableInstance.create();
        var client = NetworkTableInstance.create()) {
      server.startServer("", "127.0.0.1", 0, port);
      client.setServer("127.0.0.1", port);
      client.startClient4("bench-contract-test");
      long deadline = System.nanoTime() + 5_000_000_000L;
      while ((!client.isConnected() || client.getServerTimeOffset().isEmpty())
          && System.nanoTime() < deadline) Thread.sleep(10);
      assertThat(client.isConnected()).isTrue();
      assertThat(client.getServerTimeOffset()).isPresent();
      try (var io = new SpotVisionIO(server, fixture.profile, "robot");
          var peer = new TestPeer(client);
          var health =
              client
                  .getStructTopic("/Spot/health", Heartbeat.struct)
                  .publish(PubSubOption.sendAll(true));
          var frames =
              client
                  .getRawTopic("/Spot/front/observations")
                  .publish(
                      "struct:SpotFrameResult",
                      PubSubOption.sendAll(true),
                      PubSubOption.keepDuplicates(true))) {
        io.setTagSelection(fixture.io.selection);
        io.readInputs(now(), false);
        peer.acknowledgement(fixture.io.ack);
        var service = SpotProtocol.token("service");
        var runtime = SpotProtocol.token("runtime");
        health.set(
            new Heartbeat(service[0], service[1], runtime[0], runtime[1], 1, 0, 1, 0, 0, 1, 1, 0));
        client.flush();
        deadline = System.nanoTime() + 2_000_000_000L;
        VisionIO.Inputs inputs;
        long heartbeatSequence = 1;
        do {
          health.set(
              new Heartbeat(
                  service[0],
                  service[1],
                  runtime[0],
                  runtime[1],
                  ++heartbeatSequence,
                  0,
                  1,
                  0,
                  0,
                  1,
                  1,
                  0));
          client.flush();
          Thread.sleep(5);
          inputs = io.readInputs(now(), false);
        } while (!inputs.health().available() && System.nanoTime() < deadline);
        assertThat(inputs.health().available()).as(inputs.health().reason()).isTrue();
        fixture.frame("front", 1, 10.01);
        fixture.frame("front", 1, 10.02);
        long captureUs = NetworkTablesJNI.now() - 30_000;
        frames.set(
            TestPeer.frame(
                fixture.io.samples.get(0).observation(), fixture.io.ack, fixture.profile),
            captureUs);
        frames.set(
            TestPeer.frame(
                fixture.io.samples.get(1).observation(), fixture.io.ack, fixture.profile),
            captureUs + 1_000);
        frames.set(new byte[] {(byte) 0xff}, captureUs + 2_000);
        client.flush();
        var received = new ArrayList<VisionIO.Sample>();
        deadline = System.nanoTime() + 300_000_000L;
        do {
          Thread.sleep(5);
          inputs = io.readInputs(now(), false);
          received.addAll(inputs.samples());
        } while ((received.size() < 2 || io.malformedCount() == 0) && System.nanoTime() < deadline);
        assertThat(received)
            .as(
                "malformed=%s, transport=%s, acknowledgement=%s",
                io.malformedCount(), inputs.health().reason(), inputs.health().acknowledgement())
            .hasSize(2);
        assertThat(received.get(1).observation().sequence())
            .isGreaterThan(received.get(0).observation().sequence());
        assertThat(received.get(1).captureFpgaSeconds() - received.get(0).captureFpgaSeconds())
            .isCloseTo(.001, org.assertj.core.data.Offset.offset(1e-6));
        assertThat(now() - received.get(0).captureFpgaSeconds()).isBetween(0., .5);
        assertThat(io.malformedCount()).isEqualTo(1);
      }
    }
  }
}
