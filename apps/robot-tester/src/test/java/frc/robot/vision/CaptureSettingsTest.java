package frc.robot.vision;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import org.junit.jupiter.api.Test;

final class CaptureSettingsTest {
  @Test
  void captureChangesGenerateDistinctStableModeMetadata() {
    var settings = new CaptureSettings(640, 480, 30, PixelFormat.MJPEG);
    var mode = settings.toData();
    assertThat(mode.width()).isEqualTo(640);
    assertThat(mode.height()).isEqualTo(480);
    assertThat(mode.fps()).isEqualTo(30);
    assertThat(mode.pixelFormat()).isEqualTo("MJPEG");
    assertThat(mode.id()).matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,63}");
    assertThat(mode.opticalSignature()).matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,63}");
    assertThat(mode).isEqualTo(new CaptureSettings(640, 480, 30, PixelFormat.MJPEG).toData());
    for (var changed :
        List.of(
            new CaptureSettings(1280, 480, 30, PixelFormat.MJPEG),
            new CaptureSettings(640, 720, 30, PixelFormat.MJPEG),
            new CaptureSettings(640, 480, 60, PixelFormat.MJPEG),
            new CaptureSettings(640, 480, 30, PixelFormat.YUYV))) {
      assertThat(changed.toData().id()).isNotEqualTo(mode.id());
      assertThat(changed.toData().opticalSignature()).isNotEqualTo(mode.opticalSignature());
    }
  }

  @Test
  void rejectsInvalidDimensionsRatesAndMissingFormat() {
    assertThatThrownBy(() -> new CaptureSettings(0, 480, 30, PixelFormat.MJPEG))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> new CaptureSettings(640, 4097, 30, PixelFormat.MJPEG))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> new CaptureSettings(640, 480, 241, PixelFormat.MJPEG))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> new CaptureSettings(640, 480, 30, null))
        .isInstanceOf(NullPointerException.class);
  }
}
