// Move to shared folder after offseason
package frc.robot.vision.structs;

import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructGenerator.SchemaBuilder;
import edu.wpi.first.util.struct.StructSerializable;
import java.nio.ByteBuffer;

/** Fixed-layout NetworkTables data. */
public record RobotStatus(
    long sessionHigh,
    long sessionLow,
    boolean enabled,
    long sequence,
    long selectionGeneration,
    long allowedTags)
    implements StructSerializable {
  private static final String SCHEMA =
      new SchemaBuilder()
          .addField("sessionHigh", "int64")
          .addField("sessionLow", "int64")
          .addField("enabled", "bool")
          .addField("sequence", "int64")
          .addField("selectionGeneration", "int64")
          .addField("allowedTags", "int64")
          .build();

  @SuppressWarnings("ConstantNaming") // WPILib discovers this field by its conventional name.
  public static final Struct<RobotStatus> struct =
      new Struct<>() {
        @Override
        public Struct<?>[] getNested() {
          return new Struct<?>[] {};
        }

        @Override
        public String getSchema() {
          return SCHEMA;
        }

        @Override
        public int getSize() {
          return 41;
        }

        @Override
        public Class<RobotStatus> getTypeClass() {
          return RobotStatus.class;
        }

        @Override
        public String getTypeName() {
          return "SpotRobotStatus";
        }

        @Override
        public boolean isImmutable() {
          return true;
        }

        @Override
        public void pack(ByteBuffer buffer, RobotStatus value) {
          buffer.putLong(value.sessionHigh());
          buffer.putLong(value.sessionLow());
          buffer.put((byte) (value.enabled() ? 1 : 0));
          buffer.putLong(value.sequence());
          buffer.putLong(value.selectionGeneration());
          buffer.putLong(value.allowedTags());
        }

        @Override
        public RobotStatus unpack(ByteBuffer buffer) {
          return new RobotStatus(
              buffer.getLong(),
              buffer.getLong(),
              buffer.get() != 0,
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong());
        }
      };
}
