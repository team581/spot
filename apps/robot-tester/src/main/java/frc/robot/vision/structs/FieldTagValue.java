// Move to shared folder after offseason
package frc.robot.vision.structs;

import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructGenerator.SchemaBuilder;
import edu.wpi.first.util.struct.StructSerializable;
import java.nio.ByteBuffer;

/** Fixed-layout NetworkTables data. */
public record FieldTagValue(int id, Pose3d pose, double size) implements StructSerializable {
  private static final String SCHEMA =
      new SchemaBuilder()
          .addField("id", "int32")
          .addField("pose", Pose3d.struct.getTypeName())
          .addField("size", "double")
          .build();

  @SuppressWarnings("ConstantNaming") // WPILib discovers this field by its conventional name.
  public static final Struct<FieldTagValue> struct =
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
          return 68;
        }

        @Override
        public Class<FieldTagValue> getTypeClass() {
          return FieldTagValue.class;
        }

        @Override
        public String getTypeName() {
          return "SpotFieldTag";
        }

        @Override
        public boolean isImmutable() {
          return true;
        }

        @Override
        public void pack(ByteBuffer buffer, FieldTagValue value) {
          buffer.putInt(value.id());
          Pose3d.struct.pack(buffer, value.pose());
          buffer.putDouble(value.size());
        }

        @Override
        public FieldTagValue unpack(ByteBuffer buffer) {
          return new FieldTagValue(
              buffer.getInt(), Pose3d.struct.unpack(buffer), buffer.getDouble());
        }
      };
}
