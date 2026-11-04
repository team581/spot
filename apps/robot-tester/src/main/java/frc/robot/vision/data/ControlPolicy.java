// Move to shared folder after offseason
package frc.robot.vision.data;

public record ControlPolicy(
    String name, double defaultValue, boolean allowOverride, boolean required) {}
