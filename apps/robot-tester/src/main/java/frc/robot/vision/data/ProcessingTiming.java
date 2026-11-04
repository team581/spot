// Move to shared folder after offseason
package frc.robot.vision.data;

public record ProcessingTiming(
    double captureToDetectMs, double detectMs, double solveMs, double totalMs) {}
