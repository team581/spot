package com.team581.spot;

import edu.wpi.first.math.geometry.Pose3d;
import edu.wpi.first.util.struct.Struct;
import edu.wpi.first.util.struct.StructSerializable;
import java.nio.ByteBuffer;
import java.util.Optional;

/**
 * A robot pose estimate from one camera frame.
 *
 * @param primary The best-fitting robot pose.
 * @param alternate A second plausible robot pose.
 * @param tagIds IDs of the tags used, ascending.
 * @param averageTagDistance Average camera-to-tag distance, in meters.
 * @param tagArea The tags' share of the image area, from 0 to 1.
 */
public record SpotEstimate(
    Candidate primary,
    Optional<Candidate> alternate,
    int[] tagIds,
    double averageTagDistance,
    double tagArea)
    implements StructSerializable {
  /**
   * A robot pose and how well it fits the tags.
   *
   * @param pose Field-relative robot pose.
   * @param error RMS reprojection error, in pixels.
   */
  public record Candidate(Pose3d pose, double error) {}

  static long tagMask(int[] ids) {
    long mask = 0;
    for (int id : ids) {
      if (id >= 0 && id < Long.SIZE) {
        mask |= 1L << id;
      }
    }
    return mask;
  }

  static int[] tagIds(long mask) {
    var ids = new int[Long.bitCount(mask)];
    for (int i = 0; mask != 0; i++) {
      ids[i] = Long.numberOfTrailingZeros(mask);
      mask &= mask - 1;
    }
    return ids;
  }

  @SuppressWarnings("ConstantNaming") // WPILib discovers this field by name.
  public static final Struct<SpotEstimate> struct =
      new Struct<>() {
        @Override
        public Class<SpotEstimate> getTypeClass() {
          return SpotEstimate.class;
        }

        @Override
        public String getTypeName() {
          return "SpotEstimate";
        }

        @Override
        public int getSize() {
          return 2 * Pose3d.struct.getSize() + kSizeBool + kSizeInt64 + 4 * kSizeDouble;
        }

        @Override
        public String getSchema() {
          return "Pose3d primary;double primary_error;bool has_alternate;Pose3d alternate;"
              + "double alternate_error;int64 tag_ids;double average_tag_distance;double tag_area";
        }

        @Override
        public Struct<?>[] getNested() {
          return new Struct<?>[] {Pose3d.struct};
        }

        @Override
        public boolean isImmutable() {
          return true;
        }

        @Override
        public SpotEstimate unpack(ByteBuffer buffer) {
          var primary = new Candidate(Pose3d.struct.unpack(buffer), buffer.getDouble());
          boolean hasAlternate = buffer.get() != 0;
          var alternate = new Candidate(Pose3d.struct.unpack(buffer), buffer.getDouble());
          return new SpotEstimate(
              primary,
              hasAlternate ? Optional.of(alternate) : Optional.empty(),
              tagIds(buffer.getLong()),
              buffer.getDouble(),
              buffer.getDouble());
        }

        @Override
        public void pack(ByteBuffer buffer, SpotEstimate value) {
          Pose3d.struct.pack(buffer, value.primary().pose());
          buffer.putDouble(value.primary().error());
          buffer.put((byte) (value.alternate().isPresent() ? 1 : 0));
          Pose3d.struct.pack(buffer, value.alternate().map(Candidate::pose).orElse(Pose3d.kZero));
          buffer.putDouble(value.alternate().map(Candidate::error).orElse(0.0));
          buffer.putLong(tagMask(value.tagIds()));
          buffer.putDouble(value.averageTagDistance());
          buffer.putDouble(value.tagArea());
        }
      };
}
