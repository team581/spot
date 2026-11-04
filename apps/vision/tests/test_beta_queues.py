from types import SimpleNamespace

from spot_vision.queues import FairResultQueue


def packet(camera, sequence):
    return SimpleNamespace(frame=SimpleNamespace(camera_id=camera, sequence=sequence))


def test_fast_camera_cannot_evict_slow_results_and_offline_camera_does_not_delay():
    queue = FairResultQueue(["fast", "slow", "offline"], 2)
    queue.put(packet("slow", 1))
    for sequence in range(100):
        queue.put(packet("fast", sequence))
    assert len(queue) == 3
    frames = [queue.get().frame for _ in range(3)]
    assert [frame.camera_id for frame in frames] == ["fast", "slow", "fast"]
    assert [frame.sequence for frame in frames] == [98, 1, 99]
    queue.close()
    assert queue.get() is None
