package com.team581.spot;

import edu.wpi.first.util.struct.Struct;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

final class TestStructs {
  static <T> ByteBuffer pack(Struct<T> struct, T value) {
    var buffer = ByteBuffer.allocate(struct.getSize()).order(ByteOrder.LITTLE_ENDIAN);
    struct.pack(buffer, value);
    return buffer.rewind();
  }

  private TestStructs() {}
}
