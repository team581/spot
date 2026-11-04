// Move to shared folder after offseason
package frc.robot.vision.structs;

import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructGenerator.SchemaBuilder;
import edu.wpi.first.util.struct.StructSerializable;
import java.nio.ByteBuffer;

/** Atomic vision result, published by Spot and subscribed to by the robot. */
public record FrameResult(
    long contextHigh,
    long contextLow,
    long captureHigh,
    long captureLow,
    long sequence,
    long tagSelectionGeneration,
    long captureLocalNtUs,
    int timestampSource,
    double timestampUncertainty,
    long observedTags,
    int candidateCount,
    PoseEstimate primary,
    PoseEstimate alternate,
    double captureToDetectMs,
    double detectMs,
    double solveMs,
    double totalMs)
    implements StructSerializable {
  private static final String SCHEMA =
      new SchemaBuilder()
          .addField("contextHigh", "int64")
          .addField("contextLow", "int64")
          .addField("captureHigh", "int64")
          .addField("captureLow", "int64")
          .addField("sequence", "int64")
          .addField("tagSelectionGeneration", "int64")
          .addField("captureLocalNtUs", "int64")
          .addField("timestampSource", "int32")
          .addField("timestampUncertainty", "double")
          .addField("observedTags", "int64")
          .addField("candidateCount", "int32")
          .addField("primary", PoseEstimate.struct.getTypeName())
          .addField("alternate", PoseEstimate.struct.getTypeName())
          .addField("captureToDetectMs", "double")
          .addField("detectMs", "double")
          .addField("solveMs", "double")
          .addField("totalMs", "double")
          .build();

  @SuppressWarnings("ConstantNaming") // WPILib discovers this field by its conventional name.
  public static final Struct<FrameResult> struct =
      new Struct<>() {
        @Override
        public Struct<?>[] getNested() {
          return new Struct<?>[] {PoseEstimate.struct};
        }

        @Override
        public String getSchema() {
          return SCHEMA;
        }

        @Override
        public int getSize() {
          return 328;
        }

        @Override
        public Class<FrameResult> getTypeClass() {
          return FrameResult.class;
        }

        @Override
        public String getTypeName() {
          return "SpotFrameResult";
        }

        @Override
        public boolean isImmutable() {
          return true;
        }

        @Override
        public void pack(ByteBuffer buffer, FrameResult value) {
          buffer.putLong(value.contextHigh());
          buffer.putLong(value.contextLow());
          buffer.putLong(value.captureHigh());
          buffer.putLong(value.captureLow());
          buffer.putLong(value.sequence());
          buffer.putLong(value.tagSelectionGeneration());
          buffer.putLong(value.captureLocalNtUs());
          buffer.putInt(value.timestampSource());
          buffer.putDouble(value.timestampUncertainty());
          buffer.putLong(value.observedTags());
          buffer.putInt(value.candidateCount());
          PoseEstimate.struct.pack(buffer, value.primary());
          PoseEstimate.struct.pack(buffer, value.alternate());
          buffer.putDouble(value.captureToDetectMs());
          buffer.putDouble(value.detectMs());
          buffer.putDouble(value.solveMs());
          buffer.putDouble(value.totalMs());
        }

        @Override
        public FrameResult unpack(ByteBuffer buffer) {
          return new FrameResult(
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getLong(),
              buffer.getInt(),
              buffer.getDouble(),
              buffer.getLong(),
              buffer.getInt(),
              PoseEstimate.struct.unpack(buffer),
              PoseEstimate.struct.unpack(buffer),
              buffer.getDouble(),
              buffer.getDouble(),
              buffer.getDouble(),
              buffer.getDouble());
        }
      };
}
