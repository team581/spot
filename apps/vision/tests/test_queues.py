from __future__ import annotations

import numpy as np

from spot_vision.models import FramePacket
from spot_vision.queues import LatestFrameSlot


def frame(sequence: int) -> FramePacket:
    return FramePacket("front", sequence, sequence, sequence, np.zeros((8, 8, 2), dtype=np.uint8))


def test_latest_frame_slot_overwrites_old_frame():
    slot = LatestFrameSlot()
    assert not slot.put(frame(1))
    assert slot.put(frame(2))
    assert slot.take().sequence == 2
    assert slot.take() is None
