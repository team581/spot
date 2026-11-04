// Move to shared folder after offseason
package frc.robot.vision.structs;

import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructGenerator.SchemaBuilder;
import edu.wpi.first.util.struct.StructSerializable;
import java.nio.ByteBuffer;

/** Fixed-layout NetworkTables data. */
public record Heartbeat(
    long serviceHigh,
    long serviceLow,
    long runtimeHigh,
    long runtimeLow,
    long sequence,
    double uptime,
    int syncState,
    long offsetUs,
    double syncAge,
    long connectionEpoch,
    long syncEpoch,
    long discontinuities)
    implements StructSerializable {
  private static final String SCHEMA =
      new SchemaBuilder()
          .addField("serviceHigh", "int64")
          .addField("serviceLow", "int64")
          .addField("runtimeHigh", "int64")
          .addField("runtimeLow", "int64")
          .addField("sequence", "int64")
          .addField("uptime", "double")
          .addField("syncState", "int32")
          .addField("offsetUs", "int64")
          .addField("syncAge", "double")
          .addField("connectionEpoch", "int64")
          .addField("syncEpoch", "int64")
          .addField("discontinuities", "int64")
          .build();

  @SuppressWarnings("ConstantNaming") // WPILib discovers this field by its conventional name.
  public static final Struct<Heartbeat> struct =
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
          return 92;
        }

        @Override
        public Class<Heartbeat> getTypeClass() {
          return Heartbeat.class;
        }

        @Override
        public String getTypeName() {
          return "SpotHeartbeat";
        }

        @Override
        public boolean isImmutable() {
          return true;
        }

        @Override
        public void pack(ByteBuffer buffer, Heartbeat value) {
          buffer.putLong(value.serviceHigh());
          buffer.putLong(value.serviceLow());
          buffer.putLong(value.runtimeHigh());
          buffer.putLong(value.runtimeLow());
          buffer.putLong(value.sequence());
          buffer.putDouble(value.uptime());
          buffer.putInt(value.syncState());
          buffer.putLong(value.offsetUs());
          buffer.putDouble(value.syncAge());
          buffer.putLong(value.connectionEpoch());
          buffer.putLong(value.syncEpoch());
          buffer.putLong(value.discontinuities());
        }

        @Override
        public Heartbeat unpack(ByteBuffer buffer) {
          return new Heartbeat(
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getDouble(),
              buffer.getInt(),
              buffer.getLong(),
              buffer.getDouble(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong());
        }
      };
}
