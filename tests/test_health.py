from buddy_vision import health


def test_temperature_skips_unreadable_sensor(monkeypatch):
    monkeypatch.setattr(health.glob, "glob", lambda _pattern: ["bad", "good"])

    def read_text(path):
        if str(path) == "bad":
            raise TypeError("transient malformed sysfs data")
        return "42500\n"

    monkeypatch.setattr(health.Path, "read_text", read_text)

    assert health.jetson_temperature_c() == 42.5
