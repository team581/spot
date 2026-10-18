package frc.robot.vision;

import com.google.gson.*;
import edu.wpi.first.math.geometry.Translation3d;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Golden poses produced by real WPILib, also consumed by the JavaScript comparison test. */
class SpotCameraConventionTest {
  @Test void wpilibExportMatchesSharedConventionCases() throws Exception {
    double[][] rotations = {{0,0,0}, {30,0,0}, {-30,0,0}, {0,30,0}, {0,-30,0},
        {0,0,90}, {0,0,-90}, {20,30,45}, {-20,-30,-45}, {15,30,180},
        {-15,-30,-180}, {0,90,0}, {0,-90,0}};
    var cases = new ArrayList<Object>();
    int index=0;
    for (double sign : new double[]{1,-1}) for (double[] r : rotations) {
      var mount = VisionConfig.mount(sign*.3,sign*.4,sign*.5,r[0],r[1],r[2]);
      var camera = new SpotCameraConfig("case-"+index++,true,mount,0,
          new CaptureSettings(640,480,30,PixelFormat.MJPEG),List.of());
      Path output=Path.of("build/spot-camera-preview/convention-export.json");
      SpotCameraPreviewExport.write(VisionConfig.profile(List.of(camera)),output);
      var exported=JsonParser.parseString(Files.readString(output)).getAsJsonObject()
          .getAsJsonArray("cameras").get(0);
      var axes=new ArrayList<Object>();
      for (var axis : List.of(new Translation3d(1,0,0),new Translation3d(0,1,0),new Translation3d(0,0,1))) {
        var world=axis.rotateBy(mount.getRotation());
        axes.add(new double[]{world.getX(),world.getY(),world.getZ()});
      }
      cases.add(Map.of("javaRollPitchYawDeg",r,"jetsonYawPitchRollDeg",new double[]{r[2],r[1],r[0]},
          "exported",exported,"worldAxes",axes));
    }
    String json=new GsonBuilder().setPrettyPrinting().create().toJson(cases);
    Files.writeString(Path.of("build/spot-camera-preview/convention-cases.json"),json);
    try (var input=getClass().getResourceAsStream("/spot-camera-conventions.json")) {
      assertNotNull(input,"Shared convention fixture must be present");
      assertEquals(JsonParser.parseString(new String(input.readAllBytes(),StandardCharsets.UTF_8)),
          JsonParser.parseString(json),"WPILib/exporter changed; review the JS comparison before updating fixture");
    }
  }
}
