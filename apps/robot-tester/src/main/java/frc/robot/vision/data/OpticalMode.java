// Move to shared folder after offseason
package frc.robot.vision.data;

public record OpticalMode(
    String id, int width, int height, String pixelFormat, int fps, String opticalSignature) {}
