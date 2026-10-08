import json

import pytest

from spot_vision.config import ConfigError
from spot_vision.persistence import StateStore


def test_restore_rejects_corrupt_nonactive_history_even_if_json_parses(tmp_path):
    store = StateStore(tmp_path)
    first = store.commit(
        {"gain": 1}, "", apply=lambda _: None, rollback=lambda _: None, eligible=lambda: None
    )
    store.commit(
        {"gain": 2},
        first.generation,
        apply=lambda _: None,
        rollback=lambda _: None,
        eligible=lambda: None,
    )
    path = tmp_path / "generations" / f"{first.generation}.json"
    data = json.loads(path.read_bytes())
    data["data"]["gain"] = 99
    path.write_text(json.dumps(data))
    with pytest.raises(ConfigError, match="checksum"):
        store.read_generation(first.generation)


def test_tuning_does_not_evict_calibration_history_and_failed_stages_are_pruned(tmp_path):
    store = StateStore(tmp_path)

    def commit(data, expected):
        return store.commit(
            data, expected, apply=lambda _: None, rollback=lambda _: None, eligible=lambda: None
        )

    first = commit(
        {"calibrations": {"a:mode": {"identity": "a", "mode_signature": "mode", "hash": "one"}}}, ""
    )
    second = commit(
        {"calibrations": {"a:mode": {"identity": "a", "mode_signature": "mode", "hash": "two"}}},
        first.generation,
    )
    current = second
    for value in range(70):
        current = commit({**current.data, "gain": value}, current.generation)
    history = store.history()
    assert [entry["generation"] for entry in history] == [second.generation, first.generation]
    assert history[0]["active"] and not history[1]["active"]
    assert store.read_generation(first.generation).data["calibrations"]["a:mode"]["hash"] == "one"
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
