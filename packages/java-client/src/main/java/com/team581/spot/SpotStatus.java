package com.team581.spot;

import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructSerializable;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/**
 * Spot's overall status.
 *
 * @param version Spot's version.
 * @param state Spot's state. {@link Spot#error()} explains problems.
 * @param overridesActive Whether dashboard overrides change the robot's config.
 */
public record SpotStatus(String version, State state, boolean overridesActive)
    implements StructSerializable {
  /** Only cameras marked {@code required} affect Spot's state. */
  public enum State {
    READY,
    WAITING_FOR_TIME_SYNC,
    WAITING_FOR_CONFIG,
    INVALID_CONFIG,
    MISSING_CAMERA,
    UNCALIBRATED_CAMERA,
    /** A state from a newer Spot version. */
    UNKNOWN;

    private static final State[] VALUES = values();

    static State fromId(int id) {
      return id < UNKNOWN.ordinal() ? VALUES[id] : UNKNOWN;
    }
  }

  private static final int VERSION_LENGTH = 16;

  @SuppressWarnings("ConstantNaming") // WPILib discovers this field by name.
  public static final Struct<SpotStatus> struct =
      new Struct<>() {
        @Override
        public Class<SpotStatus> getTypeClass() {
          return SpotStatus.class;
        }

        @Override
        public String getTypeName() {
          return "SpotStatus";
        }

        @Override
        public int getSize() {
          return VERSION_LENGTH + 2;
        }

        @Override
        public String getSchema() {
          return "char version[16];enum {ready=0, waiting_for_time_sync=1, waiting_for_config=2,"
              + " invalid_config=3, missing_camera=4, uncalibrated_camera=5} uint8 state;"
              + "bool overrides_active";
        }

        @Override
        public boolean isImmutable() {
          return true;
        }

        @Override
        public SpotStatus unpack(ByteBuffer buffer) {
          var bytes = new byte[VERSION_LENGTH];
          buffer.get(bytes);
          int length = 0;
          while (length < bytes.length && bytes[length] != 0) {
            length++;
          }
          var version = new String(bytes, 0, length, StandardCharsets.UTF_8);
          return new SpotStatus(
              version, State.fromId(Byte.toUnsignedInt(buffer.get())), buffer.get() != 0);
        }

        @Override
        public void pack(ByteBuffer buffer, SpotStatus value) {
          buffer.put(
              Arrays.copyOf(value.version().getBytes(StandardCharsets.UTF_8), VERSION_LENGTH));
          buffer.put((byte) value.state().ordinal());
          buffer.put((byte) (value.overridesActive() ? 1 : 0));
        }
      };
}
