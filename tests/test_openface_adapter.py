import math

import pytest

from amble.tracking.openface import OpenFaceEyeTracker


def test_openface_csv_row_maps_gaze_pose_and_quality():
    tracker = OpenFaceEyeTracker("missing-for-parser-test")
    sample = tracker._row_to_sample({
        "frame": "42", "confidence": "0.91", "success": "1",
        "gaze_0_x": "0", "gaze_0_y": "0", "gaze_0_z": "-1",
        "gaze_1_x": "0.1", "gaze_1_y": "0", "gaze_1_z": "-1",
        "pose_Rx": str(math.pi / 6), "pose_Ry": "0", "pose_Rz": "0",
        "pose_Tx": "1", "pose_Ty": "2", "pose_Tz": "500",
    })
    assert sample.frame_number == 42
    assert sample.valid
    assert sample.left_gaze_x == .5
    assert sample.right_gaze_x > .5
    assert sample.head_pitch_deg == pytest.approx(30)
    assert sample.head_z_mm == 500
    assert sample.tracker_type == "openface_gaze"
