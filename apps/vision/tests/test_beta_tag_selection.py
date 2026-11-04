from types import SimpleNamespace

import pytest

from beta_fixtures import manifest
from spot_vision.beta_processing import solve_tag_selection
from spot_vision.config import ConfigError
from spot_vision.configuration import ConfigurationService, TagSelection
from spot_vision.models import PoseSolution
from spot_vision.persistence import StateStore
from spot_vision.proto import vision_v2_pb2 as wire


def configured(tmp_path):
    applications = []
    service = ConfigurationService(StateStore(tmp_path), lambda *args: applications.append(args))
    service.connection_changed(True)
    service.accept_manifest(manifest())
    return service, applications


def state(sequence=1, generation=1, ids=(1, 2), session="robot-1", enabled=True):
    return wire.RobotState(
        robot_session=session,
        enabled=enabled,
        sequence=sequence,
        tag_selection_generation=generation,
        allowed_tag_ids=ids,
    )


def test_enabled_selection_is_global_fresh_and_does_not_reapply_configuration(tmp_path):
    service, applications = configured(tmp_path)
    service.robot_state(state(), now=10)
    assert service.tag_selection(10) == TagSelection(1, (1, 2))
    with pytest.raises(ConfigError, match="locked"):
        service.require_eligible(10)
    service.robot_state(state(2, 2, (2,)), now=10.2)
    assert service.tag_selection(10.2) == TagSelection(2, (2,))
    assert len(applications) == 1
    assert service.tag_selection(12.3) is None
    service.robot_state(state(3, 2, (2,)), now=12.4)
    assert service.tag_selection(12.4) == TagSelection(2, (2,))
    service.connection_changed(False)
    assert service.tag_selection(12.4) is None


@pytest.mark.parametrize("ids", [(2, 1), (1, 1), (999,)])
def test_invalid_selection_cannot_publish_or_unlock_enabled_robot(tmp_path, ids):
    service, _ = configured(tmp_path)
    service.robot_state(state(ids=ids), now=10)
    assert service.tag_selection(10) is None
    with pytest.raises(ConfigError):
        service.require_eligible(10)


def test_old_session_sequence_and_generation_cannot_replace_current_selection(tmp_path):
    service, _ = configured(tmp_path)
    service.robot_state(state(1, 3, (2,)), now=10)
    service.robot_state(state(1, 4, (1,)), now=11)
    service.robot_state(state(2, 4, (1,), session="old"), now=11)
    assert service.tag_selection(10.1) == TagSelection(3, (2,))
    assert service.tag_selection(12.1) is None  # replay did not refresh freshness
    service.robot_state(state(2, 2, (1,)), now=12.2)
    assert service.tag_selection(12.2) is None
    service.robot_state(state(3, 2, (1,)), now=12.3)
    assert service.tag_selection(12.3) is None  # cannot lower watermark via invalid state
    service.robot_state(state(4, 3, (2,)), now=12.4)
    assert service.tag_selection(12.4) == TagSelection(3, (2,))
    service.robot_state(state(5, 3, (1,)), now=12.5)
    assert service.tag_selection(12.5) is None  # equal generation cannot change IDs


def test_mixed_detection_filters_before_solving_and_retains_exclusions():
    calls = []

    class Solver:
        def solve(self, tags):
            calls.append(tuple(tag.id for tag in tags))
            return PoseSolution(used_tag_ids=frozenset(tag.id for tag in tags))

    detections = tuple(SimpleNamespace(id=id) for id in (1, 2))
    result = solve_tag_selection(Solver(), detections, TagSelection(7, (2,)))
    assert calls == [(2,)]
    assert result.used_tag_ids == {2}
    assert result.rejection_reasons == {1: "tag-policy-excluded"}
    empty = solve_tag_selection(Solver(), detections, TagSelection(8, ()))
    assert not empty.candidates and not empty.used_tag_ids and len(calls) == 1
    unavailable = solve_tag_selection(Solver(), detections, None)
    assert not unavailable.candidates and len(calls) == 1


def test_additive_policy_golden_packets_preserve_legacy_bytes():
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).parent / "data/beta"
    expectations = json.loads((root / "policy-expectations.json").read_text())
    for name, expected in expectations.items():
        assert hashlib.sha256((root / f"{name}.bin").read_bytes()).hexdigest() == expected
    data = (root / "policy-state.bin").read_bytes()
    assert data.hex() == "0a07726f626f742d311001180720032a020102"
    request = wire.RobotState.FromString(data)
    assert request.tag_selection_generation == 3 and list(request.allowed_tag_ids) == [1, 2]
    assert request.SerializeToString() == data
    ack = (root / "policy-ack.bin").read_bytes()
    observation = (root / "policy-multi.bin").read_bytes()
    assert ack == (root / "ack.bin").read_bytes() + bytes.fromhex("6801")
    assert observation == (root / "multi.bin").read_bytes() + bytes.fromhex("c80103")
    assert wire.Acknowledgement.FromString(ack).tag_selection_supported
    assert wire.Observation.FromString(observation).tag_selection_generation == 3
