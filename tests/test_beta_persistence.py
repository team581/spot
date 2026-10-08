import json

import pytest

from spot_vision.config import ConfigError
from spot_vision.persistence import StateStore


def commit(store, data, expected="", apply=lambda _: None, eligible=lambda: None):
    return store.commit(data, expected, apply=apply, rollback=lambda _: None, eligible=eligible)


def test_group_commit_restart_and_conflict(tmp_path):
    store = StateStore(tmp_path)
    first = commit(store, {"calibrations": {"a": 1, "b": 2}})
    assert StateStore(tmp_path).load() == first
    with pytest.raises(ConfigError, match="revision conflict"):
        commit(store, {"calibrations": {"a": 3}}, "")
    assert store.load() == first


def test_failed_apply_or_changed_eligibility_keeps_complete_old_group(tmp_path):
    store = StateStore(tmp_path)
    first = commit(store, {"a": 1, "b": 2})
    rollback = []

    def fail(_):
        raise RuntimeError("one camera failed")

    with pytest.raises(RuntimeError):
        store.commit(
            {"a": 3, "b": 4},
            first.generation,
            apply=fail,
            rollback=rollback.append,
            eligible=lambda: None,
        )
    assert store.load() == first and rollback == [first]
    calls = []

    def eligibility():
        calls.append(1)
        if len(calls) > 1:
            raise ConfigError("robot enabled during apply")

    with pytest.raises(ConfigError):
        commit(store, {"a": 3, "b": 4}, first.generation, eligible=eligibility)
    assert StateStore(tmp_path).load() == first


def test_corrupt_cache_recovers_last_known_good_with_fault(tmp_path):
    store = StateStore(tmp_path)
    first = commit(store, {"a": 1})
    second = commit(store, {"a": 2}, first.generation)
    (tmp_path / "generations" / f"{second.generation}.json").write_text("broken")
    restarted = StateStore(tmp_path)
    assert restarted.load() == first and "Corrupt" in restarted.fault
    third = commit(restarted, {"a": 3}, first.generation)
    assert restarted.load() == third
    assert restarted._load_pointer("last-known-good.json") == first


def test_staged_generation_never_becomes_active_without_commit(tmp_path):
    store = StateStore(tmp_path)
    first = commit(store, {"a": 1})
    (tmp_path / "generations" / ("f" * 32 + ".json")).write_text(json.dumps({"a": 9}))
    assert StateStore(tmp_path).load() == first
