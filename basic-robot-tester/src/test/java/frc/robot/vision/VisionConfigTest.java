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
  @Test void defaultsRemainShadowWithoutInventedCameras() {
    var config = BenchConfig.create();
    assertThat(config.profile().getCamerasCount()).isZero();
    assertThat(config.mounts()).isEmpty();
    assertThat(config.profile().getFusionEnabled()).isFalse();
    assertThat(config.profile().getHeadingEnabled()).isFalse();
    assertThat(config.profile().getField().getTagsCount()).isEqualTo(32);
  }

  @Test void studentCameraSettingsReachManifestAndOwnTheirLists() {
    var controls = new ArrayList<>(List.of(Control.pinned("exposure_auto", 1), Control.tunable("gain", 5)));
    var camera = new SpotCameraConfig("front", true, VisionConfig.mount(.1, 0, .3, 0, 0, 90),
        180, new CaptureSettings(640, 480, 30, PixelFormat.MJPEG), controls);
    controls.clear();
    var profile = VisionConfig.profile(List.of(camera));
    var definition = profile.getCameras(0);
    assertThat(definition.getName()).isEqualTo("front");
    assertThat(definition.getRequired()).isTrue();
    assertThat(definition.getImageRotationDeg()).isEqualTo(180);
    assertThat(definition.getAllowedModesCount()).isEqualTo(1);
    assertThat(definition.getControls(0).getAllowOverride()).isFalse();
    assertThat(definition.getControls(1).getAllowOverride()).isTrue();
    assertThat(SpotProtocol.pose(definition.getRobotToCamera()).getRotation().getZ())
        .isCloseTo(Math.PI / 2, offset(1e-12));
    assertThatThrownBy(() -> VisionConfig.profile(List.of(camera, camera)))
        .isInstanceOf(IllegalArgumentException.class);
    assertThat(SpotProtocol.hash(profile))
        .isEqualTo(SpotProtocol.hash(VisionConfig.profile(List.of(camera))));
  }

  @Test void invalidCaptureSettingsAndControlsFailBeforePublication() {
    assertThatThrownBy(() -> new CaptureSettings(641, 480, 30, PixelFormat.MJPEG))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> new CaptureSettings(640, 480, 0, PixelFormat.MJPEG))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> Control.pinned("gain", Double.NaN))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> new SpotCameraConfig("front", true,
        VisionConfig.mount(0, 0, .3, 0, 0, 0), 90, new CaptureSettings(640, 480, 30, PixelFormat.MJPEG), List.of()))
        .isInstanceOf(IllegalArgumentException.class);
  }
}
