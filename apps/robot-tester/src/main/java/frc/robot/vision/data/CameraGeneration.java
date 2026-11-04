// Move to shared folder after offseason
package frc.robot.vision.data;

public record CameraGeneration(
    String cameraName,
    String bindingId,
    long bindingGeneration,
    String calibrationHash,
    String modeId,
    String opticalSignature,
    boolean calibrationValid) {}
