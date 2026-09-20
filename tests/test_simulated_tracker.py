import time

from amble.tracking import SimulatedEyeTracker


def test_simulator_emits_complete_binocular_sample():
    tracker = SimulatedEyeTracker(sample_rate_hz=1000)
    tracker.connect(); tracker.set_target(.2, .8); tracker.start_stream()
    sample = tracker.get_sample()
    assert sample is not None
    assert sample.valid
    assert sample.left_gaze_x is not None
    assert sample.right_gaze_x is not None
    assert sample.binocular_gaze_x is not None
    assert sample.tracker_time_ns is not None
    tracker.disconnect()

