"""Record a short real-camera quality stream and verify persisted provenance."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from amble.core.domain import ExperimentConfig, ExperimentKind
from amble.storage.store import DataStore
from amble.tracking import WebcamEyeTracker


QUALITY_COLUMNS = {
    "left_eye_valid", "right_eye_valid", "binocular_valid",
    "left_eye_quality", "right_eye_quality", "overall_quality",
    "left_eye_openness", "right_eye_openness",
    "left_eye_pixel_width", "right_eye_pixel_width",
    "left_eye_sharpness", "right_eye_sharpness",
    "left_eye_lighting", "right_eye_lighting", "lighting_quality",
    "head_pose_valid", "face_quality", "distance_quality",
    "tracking_guidance", "quality_reasons", "quality_threshold",
}


def main(root: str, camera_index: int = 0) -> int:
    store = DataStore(Path(root))
    tracker = WebcamEyeTracker(); tracker.connect(camera_index); tracker.start_stream()
    config = ExperimentConfig("Hardware quality check", ExperimentKind.FIXATION, duration_s=1)
    recorder = store.create_session("P-HARDWARE-CHECK", config, tracker.tracker_type)
    deadline = time.time() + 8
    try:
        while recorder.sample_count < 30 and time.time() < deadline:
            sample = tracker.get_sample()
            if sample is None: continue
            sample.target_x = .5; sample.target_y = .5; sample.experiment_phase = "pre"
            recorder.append(sample)
    finally:
        recorder.close(); tracker.disconnect()
    frame = store.load_samples(recorder.session_id)
    missing = QUALITY_COLUMNS - set(frame.columns)
    print("ROWS", len(frame)); print("MISSING_QUALITY_COLUMNS", sorted(missing))
    print("OPENNESS", sorted(frame.left_eye_openness.unique()), sorted(frame.right_eye_openness.unique()))
    print("QUALITY_RANGE", float(frame.overall_quality.min()), float(frame.overall_quality.max()))
    print("INVALID_ROWS_RETAINED", int((~frame.binocular_valid.astype(bool)).sum()))
    print("PARQUET", store.raw_path(recorder.session_id).suffix == ".parquet")
    print("CAMERA_RELEASED", not tracker.status().camera_open)
    return 0 if len(frame) == 30 and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0))
