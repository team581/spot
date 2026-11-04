import pytest

from spot_vision.clock import FrameRateCounter


@pytest.mark.parametrize(
    "timestamps",
    [
        [i / 20 for i in range(21)],
        [0.0] + [t for i in range(10) for t in (i / 10 + 0.001, (i + 1) / 10)],
    ],
)
def test_frame_rate_counts_elapsed_time_for_regular_and_burst_delivery(timestamps):
    rate = FrameRateCounter()
    for timestamp in timestamps:
        fps = rate.update(timestamp)
    # Both streams complete 20 intervals in one second. Averaging 1/dt for
    # the burst stream would incorrectly report hundreds of FPS.
    assert fps == pytest.approx(20)


def test_frame_rate_waits_for_full_window_and_counts_stalls():
    rate = FrameRateCounter()
    assert rate.update(0) == 0
    assert rate.update(0.5) == 0
    assert rate.update(5) == pytest.approx(0.4)
    assert rate.update(5.001) == pytest.approx(0.4)
    assert rate.update(6) == pytest.approx(2)
