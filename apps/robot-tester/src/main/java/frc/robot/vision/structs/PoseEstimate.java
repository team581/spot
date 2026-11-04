// Move to shared folder after offseason
package frc.robot.vision.structs;

import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructGenerator.SchemaBuilder;
import edu.wpi.first.util.struct.StructSerializable;
import java.nio.ByteBuffer;

/** Fixed-layout NetworkTables data. */
public record PoseEstimate(
    Pose3d pose,
    int method,
    long tagMask,
    double reprojectionError,
    double averageDistance,
    double imageArea,
    double imageSpread,
    double distortion)
    implements StructSerializable {
  private static final String SCHEMA =
      new SchemaBuilder()
          .addField("pose", Pose3d.struct.getTypeName())
          .addField("method", "int32")
          .addField("tagMask", "int64")
          .addField("reprojectionError", "double")
          .addField("averageDistance", "double")
          .addField("imageArea", "double")
          .addField("imageSpread", "double")
          .addField("distortion", "double")
          .build();

  @SuppressWarnings("ConstantNaming") // WPILib discovers this field by its conventional name.
  public static final Struct<PoseEstimate> struct =
      new Struct<>() {
        @Override
        public Struct<?>[] getNested() {
          return new Struct<?>[] {Pose3d.struct};
        }

        @Override
        public String getSchema() {
          return SCHEMA;
        }

        @Override
        public int getSize() {
          return 108;
        }

        @Override
        public Class<PoseEstimate> getTypeClass() {
          return PoseEstimate.class;
        }

        @Override
        public String getTypeName() {
          return "SpotPoseEstimate";
        }

        @Override
        public boolean isImmutable() {
          return true;
        }

        @Override
        public void pack(ByteBuffer buffer, PoseEstimate value) {
          Pose3d.struct.pack(buffer, value.pose());
          buffer.putInt(value.method());
          buffer.putLong(value.tagMask());
          buffer.putDouble(value.reprojectionError());
          buffer.putDouble(value.averageDistance());
          buffer.putDouble(value.imageArea());
          buffer.putDouble(value.imageSpread());
          buffer.putDouble(value.distortion());
        }

        @Override
        public PoseEstimate unpack(ByteBuffer buffer) {
          return new PoseEstimate(
              Pose3d.struct.unpack(buffer),
              buffer.getInt(),
              buffer.getLong(),
              buffer.getDouble(),
              buffer.getDouble(),
              buffer.getDouble(),
              buffer.getDouble(),
              buffer.getDouble());
        }
      };
}
