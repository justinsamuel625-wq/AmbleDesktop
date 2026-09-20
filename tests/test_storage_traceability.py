import json

import pandas as pd

from amble.domain import EyeSample, ExperimentConfig, ExperimentKind
from amble.storage import DataStore


def test_raw_rows_survive_csv_and_parquet_finalization(tmp_path):
    store = DataStore(tmp_path)
    config = ExperimentConfig("Fixation", ExperimentKind.FIXATION, duration_s=1)
    recorder = store.create_session("P-TEST", config, "simulated")
    for index in range(10):
        recorder.append(EyeSample(
            timestamp_ns=1_000_000_000 + index,
            target_x=.5, target_y=.5,
            left_gaze_x=.49, left_gaze_y=.5,
            right_gaze_x=.51, right_gaze_y=.5,
            binocular_gaze_x=.5, binocular_gaze_y=.5,
            left_confidence=.9, right_confidence=.9,
            frame_number=index, valid=True, experiment_phase="pre",
            left_eye_valid=True, right_eye_valid=index != 4, binocular_valid=index != 4,
            left_eye_quality=.9, right_eye_quality=.2 if index == 4 else .9,
            overall_quality=.2 if index == 4 else .9,
            left_eye_openness="OPEN", right_eye_openness="CLOSED" if index == 4 else "OPEN",
            left_eye_pixel_width=62, right_eye_pixel_width=59,
            left_eye_sharpness=110, right_eye_sharpness=105,
            left_eye_lighting="GOOD", right_eye_lighting="GOOD", lighting_quality="GOOD",
            head_pose_valid=True, distance_quality="IDEAL", tracking_guidance="Open right eye fully" if index == 4 else "Tracking quality good",
            quality_reasons='{"right":["openness closed"]}' if index == 4 else "{}",
        ))
    recorder.event(1_000_000_004, "test_marker", "pre", {"source": "test"})
    session_dir = recorder.close()
    loaded = store.load_samples(recorder.session_id)
    original_csv = pd.read_csv(session_dir / "raw_eye_tracking.csv")
    assert len(loaded) == len(original_csv) == 10
    assert loaded["timestamp_ns"].tolist() == original_csv["timestamp_ns"].tolist()
    assert loaded["frame_number"].tolist() == list(range(10))
    rejected = loaded.loc[loaded["frame_number"] == 4].iloc[0]
    assert not bool(rejected["binocular_valid"])
    assert rejected["right_eye_openness"] == "CLOSED"
    assert rejected["right_eye_quality"] == .2
    assert "openness closed" in rejected["quality_reasons"]
    metadata = json.loads((session_dir / "metadata.json").read_text())
    assert metadata["sample_count"] == 10
    assert metadata["software_version"] == "0.1.0"
