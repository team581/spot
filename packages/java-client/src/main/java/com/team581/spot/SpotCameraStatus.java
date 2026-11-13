package com.team581.spot;

import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructSerializable;
import java.nio.ByteBuffer;

/**
 * A camera's status.
 *
 * @param state The camera's state. {@link Spot#error()} explains problems with required cameras.
 * @param fps Frames processed per second.
 * @param droppedFrames Frames dropped because detection fell behind capture.
 */
public record SpotCameraStatus(State state, double fps, long droppedFrames)
    implements StructSerializable {
  public enum State {
    STREAMING,
    DISCONNECTED,
    DUPLICATE_SERIAL,
    UNCALIBRATED,
    FALLING_BEHIND,
    /** A state from a newer Spot version. */
    UNKNOWN;

    private static final State[] VALUES = values();

    static State fromId(int id) {
      return id < UNKNOWN.ordinal() ? VALUES[id] : UNKNOWN;
    }
  }

  @SuppressWarnings("ConstantNaming") // WPILib discovers this field by name.
  public static final Struct<SpotCameraStatus> struct =
      new Struct<>() {
        @Override
        public Class<SpotCameraStatus> getTypeClass() {
          return SpotCameraStatus.class;
        }

        @Override
        public String getTypeName() {
          return "SpotCameraStatus";
        }

        @Override
        public int getSize() {
          return 1 + kSizeDouble + kSizeInt32;
        }

        @Override
        public String getSchema() {
          return "enum {streaming=0, disconnected=1, duplicate_serial=2, uncalibrated=3,"
              + " falling_behind=4} uint8 state;double fps;uint32 dropped_frames";
        }

        @Override
        public boolean isImmutable() {
          return true;
        }

        @Override
        public SpotCameraStatus unpack(ByteBuffer buffer) {
          return new SpotCameraStatus(
              State.fromId(Byte.toUnsignedInt(buffer.get())),
              buffer.getDouble(),
              Integer.toUnsignedLong(buffer.getInt()));
        }

        @Override
        public void pack(ByteBuffer buffer, SpotCameraStatus value) {
          buffer.put((byte) value.state().ordinal());
          buffer.putDouble(value.fps());
          buffer.putInt((int) value.droppedFrames());
        }
      };
}
