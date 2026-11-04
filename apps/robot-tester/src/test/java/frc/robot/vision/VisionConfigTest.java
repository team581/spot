package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.data.Offset.offset;

import frc.robot.BenchConfig;
import frc.robot.vision.SpotCameraConfig.Control;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

class VisionConfigTest {
  @Test
  void configuredCamerasAndFlagsReachBenchWithoutDuplicatedMounts() {
    var config = BenchConfig.create();
    assertThat(config.profile().cameras().size()).isEqualTo(VisionConfig.CAMERAS.size());
    assertThat(config.mounts()).hasSize(VisionConfig.CAMERAS.size());
    assertThat(config.profile().fusionEnabled()).isEqualTo(VisionConfig.FUSION_ENABLED);
    assertThat(config.profile().headingEnabled()).isFalse();
    assertThat(config.profile().field().tags().size())
        .isEqualTo(VisionConfig.FIELD_LAYOUT.getTags().size());
  }

  @Test
  void invalidCaptureSettingsAndControlsFailBeforePublication() {
    assertThatThrownBy(() -> new CaptureSettings(641, 480, 30, PixelFormat.MJPEG))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> new CaptureSettings(640, 480, 0, PixelFormat.MJPEG))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> Control.pinned("gain", Double.NaN))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() ->
            new SpotCameraConfig(
                "front",
                true,
                VisionConfig.mount(0, 0, .3, 0, 0, 0),
                90,
                new CaptureSettings(640, 480, 30, PixelFormat.MJPEG),
                List.of()))
        .isInstanceOf(IllegalArgumentException.class);
  }

  @Test
  void studentCameraSettingsReachManifestAndOwnTheirLists() {
    var controls =
        new ArrayList<>(List.of(Control.pinned("exposure_auto", 1), Control.tunable("gain", 5)));
    var camera =
        new SpotCameraConfig(
            "front",
            true,
            VisionConfig.mount(.1, 0, .3, 0, 0, 90),
            180,
            new CaptureSettings(640, 480, 30, PixelFormat.MJPEG),
            controls);
    controls.clear();
    var profile = VisionConfig.profile(List.of(camera));
    var definition = profile.cameras().get(0);
    assertThat(definition.name()).isEqualTo("front");
    assertThat(definition.required()).isTrue();
    assertThat(definition.imageRotationDeg()).isEqualTo(180);
    assertThat(definition.allowedModes().size()).isEqualTo(1);
    assertThat(definition.controls().get(0).allowOverride()).isFalse();
    assertThat(definition.controls().get(1).allowOverride()).isTrue();
    assertThat(SpotProtocol.pose(definition.robotToCamera()).getRotation().getZ())
        .isCloseTo(Math.PI / 2, offset(1e-12));
    assertThatThrownBy(() -> VisionConfig.profile(List.of(camera, camera)))
        .isInstanceOf(IllegalArgumentException.class);
    assertThat(SpotProtocol.hash(profile))
        .isEqualTo(SpotProtocol.hash(VisionConfig.profile(List.of(camera))));
  }
}
