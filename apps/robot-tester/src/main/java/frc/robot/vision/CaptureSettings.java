package frc.robot.vision;

import frc.robot.vision.data.*;
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

  OpticalMode toData() {
    String settings = width + "x" + height + "-" + fps + "-" + pixelFormat.name();
    return new OpticalMode(
        "capture-" + settings, width, height, pixelFormat.name(), fps, "capture-v1-" + settings);
  }
}
