// Move to shared folder after offseason
package frc.robot.vision.data;

import java.util.List;

public record Acknowledgement(
    String robotId,
    String robotSession,
    String manifestHash,
    String serviceSession,
    long connectionEpoch,
    long syncEpoch,
    String runtimeGeneration,
    String fieldHash,
    List<CameraGeneration> cameras,
    boolean applied,
    String error,
    boolean tagSelectionSupported) {
  public Acknowledgement {
    cameras = List.copyOf(cameras);
  }
}
