package frc.robot.vision;

import frc.robot.vision.generated.SpotProtos;
import java.util.Objects;

/** One explicit USB capture configuration; protocol mode metadata is generated internally. */
public record CaptureSettings(int width, int height, int fps, PixelFormat pixelFormat) {
  public CaptureSettings {
    Objects.requireNonNull(pixelFormat, "pixel format required");
    if (width <= 0
        || width > 4096
        || width % 2 != 0
        || height <= 0
        || height > 4096
        || fps <= 0
        || fps > 240) throw new IllegalArgumentException("invalid capture settings");
  }

  SpotProtos.OpticalMode toProto() {
    String settings = width + "x" + height + "-" + fps + "-" + pixelFormat.name();
    return SpotProtos.OpticalMode.newBuilder()
        .setId("capture-" + settings)
        .setWidth(width)
        .setHeight(height)
        .setFps(fps)
        .setPixelFormat(pixelFormat.name())
        .setOpticalSignature("capture-v1-" + settings)
        .build();
  }
}
