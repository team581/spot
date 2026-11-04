package frc.robot.vision;

/** Copies immutable test inputs while changing only the values under test. */
final class TestRecords {
  static <T extends Record> T with(T value, Object... changes) {
    var components = value.getClass().getRecordComponents();
    var arguments = new Object[components.length];
    var types = new Class<?>[components.length];
    try {
      for (int i = 0; i < components.length; i++) {
        arguments[i] = components[i].getAccessor().invoke(value);
        types[i] = components[i].getType();
      }
      for (int c = 0; c < changes.length; c += 2) {
        int index = 0;
        while (index < components.length && !components[index].getName().equals(changes[c]))
          index++;
        if (index == components.length)
          throw new IllegalArgumentException("Unknown record component: " + changes[c]);
        arguments[index] = changes[c + 1];
      }
      @SuppressWarnings("unchecked")
      T result = (T) value.getClass().getConstructor(types).newInstance(arguments);
      return result;
    } catch (ReflectiveOperationException exception) {
      throw new IllegalStateException(exception);
    }
  }

  private TestRecords() {}
}
