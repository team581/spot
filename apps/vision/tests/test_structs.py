"""Standalone checks for the shared struct contract."""

import pytest


def test_geometry_survives_native_struct_roundtrip():
    from wpimath.geometry import Pose3d, Rotation3d
    from wpiutil.wpistruct import pack, unpack

    for rotation in (Rotation3d(0.37, -0.82, 1.93), Rotation3d(-2.8, 0.4, -0.17)):
        pose = Pose3d(1.0, 2.0, 3.0, rotation)
        decoded = unpack(Pose3d, pack(pose))
        assert decoded.translation().distance(pose.translation()) < 1e-12
        assert abs((decoded.rotation() - pose.rotation()).getQuaternion().W()) == pytest.approx(1)


def test_tag_masks_preserve_arbitrary_ids_and_the_signed_high_bit():
    from spot_vision import protocol_models as wire
    from spot_vision.structs import tag_ids, tag_mask

    ids = [1, *range(100, 162), 65535]
    layout = wire.FieldLayout(tags=[wire.FieldTag(id=tag_id) for tag_id in ids])
    mask = tag_mask([1, 65535], layout)
    assert mask == -(1 << 63) + 1
    assert tag_ids(mask, layout) == [1, 65535]
    with pytest.raises(ValueError, match="exceeds"):
        tag_ids(4, wire.FieldLayout(tags=layout.tags[:2]))
