package frc.robot.vision;

import com.google.gson.Gson;
import java.nio.file.*;
import java.util.*;

/** Desktop-only export. Never initializes Robot or hardware. */
public final class SpotCameraPreviewExport {
  public static void main(String[] args) throws Exception {
    write(VisionConfig.profile(), Path.of(args[0]));
  }

  static void write(frc.robot.vision.generated.SpotProtos.Profile profile, Path output) throws Exception {
    var cameras = new ArrayList<Object>();
    for (var camera : profile.getCamerasList()) {
      var pose = camera.getRobotToCamera();
      double norm = Math.sqrt(pose.getQw()*pose.getQw()+pose.getQx()*pose.getQx()
          +pose.getQy()*pose.getQy()+pose.getQz()*pose.getQz());
      if (!Double.isFinite(norm) || norm == 0) throw new IllegalArgumentException("Invalid quaternion");
      var modes = new ArrayList<Object>();
      for (var mode : camera.getAllowedModesList()) modes.add(Map.of(
          "width", mode.getWidth(), "height", mode.getHeight(), "fps", mode.getFps(),
          "pixelFormat", mode.getPixelFormat()));
      var controls = new ArrayList<Object>();
      for (var control : camera.getControlsList()) controls.add(Map.of(
          "name", control.getName(), "value", control.getDefaultValue(),
          "required", control.getRequired(), "allowOverride", control.getAllowOverride()));
      cameras.add(Map.of("name", camera.getName(), "required", camera.getRequired(),
          "translation", new double[]{pose.getXM(), pose.getYM(), pose.getZM()},
          "quaternion", new double[]{pose.getQw()/norm,pose.getQx()/norm,pose.getQy()/norm,pose.getQz()/norm},
          "imageRotationDeg", camera.getImageRotationDeg(), "capture", modes, "controls", controls));
    }
    Path target = output.toAbsolutePath();
    Files.createDirectories(target.getParent());
    Path temp = Files.createTempFile(target.getParent(), "preview-", ".json");
    try {
      Files.writeString(temp, new Gson().toJson(Map.of("schemaVersion", 1,
          "robotId", profile.getRobotId(), "cameras", cameras)));
      Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    } finally { Files.deleteIfExists(temp); }
  }
  private SpotCameraPreviewExport() {}
}
