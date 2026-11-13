package com.team581.spot;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.team581.spot.SpotEstimate.Candidate;
import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.math.geometry.Rotation3d;
import edu.wpi.first.util.struct.DynamicStruct;
import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructDescriptorDatabase;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Pattern;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Checks the Java structs against the schemas Spot publishes, from the vision service source. */
class SchemaContractTest {
  private static final List<Struct<?>> STRUCTS =
      List.of(SpotStatus.struct, SpotCameraStatus.struct, SpotEstimate.struct);

  private final Map<String, String> rustSchemas = new LinkedHashMap<>();
  private final StructDescriptorDatabase database = new StructDescriptorDatabase();

  @BeforeEach
  void readRustSchemas() throws Exception {
    var source = Files.readString(Path.of(System.getProperty("spot.structs")));
    var tuple = Pattern.compile("\\(\\s*\"(\\w+)\",\\s*\"((?:[^\"\\\\]|\\\\.)*)\"", Pattern.DOTALL);
    var matcher = tuple.matcher(source);
    while (matcher.find()) {
      // A backslash at the end of a Rust string line skips the newline and leading whitespace.
      rustSchemas.put(matcher.group(1), matcher.group(2).replaceAll("\\\\\\R\\s*", ""));
    }
    // Spot lists dependencies first.
    for (var schema : rustSchemas.entrySet()) {
      database.add(schema.getKey(), schema.getValue());
    }
  }

  @Test
  void javaStructsMatchSpotSchemas() {
    var spotStructs =
        rustSchemas.keySet().stream().filter(name -> name.startsWith("Spot")).toList();
    assertEquals(spotStructs, STRUCTS.stream().map(Struct::getTypeName).toList());
    for (var struct : STRUCTS) {
      var name = struct.getTypeName();
      assertEquals(rustSchemas.get(name), struct.getSchema(), name);
      assertEquals(database.find(name).getSize(), struct.getSize(), name);
    }
  }

  @Test
  void statusFieldsMatchSchema() {
    var status = new SpotStatus("2026.0.0", SpotStatus.State.MISSING_CAMERA, true);
    var buffer = TestStructs.pack(SpotStatus.struct, status);
    var dynamic = DynamicStruct.wrap(database.find("SpotStatus"), buffer);

    assertEquals("2026.0.0", dynamic.getStringField(dynamic.findField("version")));
    assertEquals(4, dynamic.getIntField(dynamic.findField("state")));
    assertTrue(dynamic.getBoolField(dynamic.findField("overrides_active")));
    assertEquals(status, SpotStatus.struct.unpack(buffer.rewind()));
  }

  @Test
  void cameraStatusFieldsMatchSchema() {
    var status = new SpotCameraStatus(SpotCameraStatus.State.FALLING_BEHIND, 118.5, 3_000_000_000L);
    var buffer = TestStructs.pack(SpotCameraStatus.struct, status);
    var dynamic = DynamicStruct.wrap(database.find("SpotCameraStatus"), buffer);

    assertEquals(4, dynamic.getIntField(dynamic.findField("state")));
    assertEquals(118.5, dynamic.getDoubleField(dynamic.findField("fps")));
    assertEquals(3_000_000_000L, dynamic.getIntField(dynamic.findField("dropped_frames")));
    assertEquals(status, SpotCameraStatus.struct.unpack(buffer.rewind()));
  }

  @Test
  void estimateFieldsMatchSchema() {
    var primary = new Candidate(new Pose3d(1, 2, 0.1, new Rotation3d(0, 0, 0.5)), 0.25);
    var alternate = new Candidate(new Pose3d(4, 5, 0.2, new Rotation3d(0, 0, -0.5)), 0.75);
    var estimate =
        new SpotEstimate(primary, Optional.of(alternate), new int[] {0, 7, 63}, 2.5, 0.01);
    var buffer = TestStructs.pack(SpotEstimate.struct, estimate);
    var dynamic = DynamicStruct.wrap(database.find("SpotEstimate"), buffer);

    assertEquals(0.25, dynamic.getDoubleField(dynamic.findField("primary_error")));
    assertTrue(dynamic.getBoolField(dynamic.findField("has_alternate")));
    var alternatePose = dynamic.getStructField(dynamic.findField("alternate"));
    var translation = alternatePose.getStructField(alternatePose.findField("translation"));
    assertEquals(4, translation.getDoubleField(translation.findField("x")));
    assertEquals(0.75, dynamic.getDoubleField(dynamic.findField("alternate_error")));
    assertEquals(1L | 1L << 7 | 1L << 63, dynamic.getIntField(dynamic.findField("tag_ids")));
    assertEquals(2.5, dynamic.getDoubleField(dynamic.findField("average_tag_distance")));
    assertEquals(0.01, dynamic.getDoubleField(dynamic.findField("tag_area")));

    var unpacked = SpotEstimate.struct.unpack(buffer.rewind());
    assertEquals(primary, unpacked.primary());
    assertEquals(Optional.of(alternate), unpacked.alternate());
    assertArrayEquals(new int[] {0, 7, 63}, unpacked.tagIds());
  }
}
