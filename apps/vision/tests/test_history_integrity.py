import pytest

from spot_vision.config import ConfigError
from spot_vision.persistence import StateStore


def test_history_ids_cannot_escape_the_history_directory(tmp_path):
    with pytest.raises(ConfigError, match="Invalid history"):
        StateStore(tmp_path).read_generation("../state")


def test_tuning_does_not_evict_calibration_history_and_failed_stages_are_pruned(tmp_path):
    store = StateStore(tmp_path)

    def commit(data, expected):
        return store.commit(
            data, expected, apply=lambda _: None, rollback=lambda _: None, eligible=lambda: None
        )

    first = commit(
        {"calibrations": {"a:mode": {"identity": "a", "mode_signature": "mode", "id": "one"}}}, ""
    )
    second = commit(
        {"calibrations": {"a:mode": {"identity": "a", "mode_signature": "mode", "id": "two"}}},
        first.generation,
    )
    current = second
    for value in range(70):
        current = commit({**current.data, "gain": value}, current.generation)
    history = store.history()
    assert {entry["generation"]: entry["active"] for entry in history} == {
        first.generation: False,
        second.generation: True,
    }
    assert store.read_generation(first.generation).data["calibrations"]["a:mode"]["id"] == "one"
    assert len(list(store.generations.glob("*.json"))) <= 67
    with pytest.raises(RuntimeError):
        store.commit(
            {**current.data, "gain": 999},
            current.generation,
            apply=lambda _: (_ for _ in ()).throw(RuntimeError("readback failed")),
            rollback=lambda _: None,
            eligible=lambda: None,
        )
    assert store.load() == current and len(list(store.generations.glob("*.json"))) <= 67
