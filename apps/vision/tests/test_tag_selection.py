from types import SimpleNamespace

import pytest

from robot_fixtures import manifest
from spot_vision import protocol_models as wire
from spot_vision.configuration import ConfigurationService, TagSelection
from spot_vision.models import PoseSolution
from spot_vision.persistence import StateStore
from spot_vision.processing import solve_tag_selection


def configured(tmp_path):
    applications = []
    service = ConfigurationService(StateStore(tmp_path), lambda *args: applications.append(args))
    service.connection_changed(True)
    service.accept_manifest(manifest())
    return service, applications


def state(generation=1, ids=(1, 2)):
    return wire.RobotState(tag_selection_generation=generation, allowed_tag_ids=list(ids))


def test_selection_changes_do_not_reapply_configuration(tmp_path):
    service, applications = configured(tmp_path)
    service.robot_state(state())
    assert service.tag_selection() == TagSelection(1, (1, 2))
    service.require_eligible()
    service.robot_state(state(2, (2,)))
    assert service.tag_selection() == TagSelection(2, (2,))
    assert len(applications) == 1
    service.connection_changed(False)
    assert service.tag_selection() is None


@pytest.mark.parametrize("ids", [(2, 1), (1, 1), (999,)])
def test_invalid_selection_cannot_publish(tmp_path, ids):
    service, _ = configured(tmp_path)
    service.robot_state(state(ids=ids))
    assert service.tag_selection() is None


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


def test_policy_struct_fixture_preserves_selection_generation_and_mask():
    from pathlib import Path

    from wpiutil.wpistruct import unpack

    from spot_vision.structs import FrameResult, RobotStatus

    root = Path(__file__).parent / "data/robot"
    data = (root / "policy-state.bin").read_bytes()
    request = unpack(RobotStatus, data)
    assert request.selectionGeneration == 3 and request.allowedTags == 3
    observation = unpack(FrameResult, (root / "policy-multi.bin").read_bytes())
    assert observation.tagSelectionGeneration == 3
    assert observation.primary.tagMask == 3
