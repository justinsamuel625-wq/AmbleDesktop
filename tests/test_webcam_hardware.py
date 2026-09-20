import numpy as np
import pytest
from types import SimpleNamespace

from amble.tracking import webcam
from amble.tracking.webcam import WebcamEyeTracker, validate_opencv


def test_project_opencv_has_required_api_and_valid_cascades():
    info = validate_opencv()
    assert info.version.startswith("4.")
    assert info.cascade_classifier_available
    assert info.video_capture_available
    assert info.face_cascade_loaded
    assert info.eye_cascade_loaded
    assert "MediaPipe Face Landmarker" in info.landmark_backend
    assert info.landmark_model_path.endswith("face_landmarker.task")
    assert ".venv" in info.python_executable
    assert ".venv" in info.module_path


class FakeCapture:
    def __init__(self, opened, frame=None, backend="TEST"):
        self.opened = opened
        self.frame = frame
        self.backend = backend
        self.released = False

    def isOpened(self): return self.opened and not self.released
    def read(self): return (self.frame is not None, self.frame)
    def release(self): self.released = True
    def getBackendName(self): return self.backend
    def get(self, prop): return self.frame.shape[1] if prop == webcam.cv2.CAP_PROP_FRAME_WIDTH else self.frame.shape[0]


def test_camera_backend_probe_uses_first_backend_that_reads_a_frame(monkeypatch):
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    attempts = []
    captures = []

    def factory(index, backend):
        attempts.append((index, backend))
        cap = FakeCapture(opened=backend == 22, frame=frame if backend == 22 else None, backend="WORKING")
        captures.append(cap)
        return cap

    monkeypatch.setattr(webcam, "_backend_candidates", lambda: [("first", 11), ("second", 22)])
    monkeypatch.setattr(webcam.cv2, "VideoCapture", factory)
    cap, backend, first_frame = webcam._open_camera(3)
    assert attempts == [(3, 11), (3, 22)]
    assert captures[0].released
    assert backend == "WORKING"
    assert first_frame.shape == (240, 320, 3)
    cap.release()


class FakeLandmarker:
    def __init__(self, result): self.result = result
    def detect_for_video(self, image, timestamp_ms): return self.result
    def close(self): pass


def landmark_result():
    landmarks = [SimpleNamespace(x=.5, y=.5, z=0) for _ in range(478)]
    landmarks[0] = SimpleNamespace(x=.2, y=.2, z=0)
    landmarks[1] = SimpleNamespace(x=.8, y=.8, z=0)

    def place(indices, cx, cy, rx=.055, ry=.022):
        for step, index in enumerate(indices):
            angle = 2 * np.pi * step / len(indices)
            landmarks[index] = SimpleNamespace(x=cx + rx * np.cos(angle), y=cy + ry * np.sin(angle), z=0)

    place(webcam.LEFT_EYE_OUTLINE, .62, .42)
    place(webcam.RIGHT_EYE_OUTLINE, .38, .42)
    for indices, cx in [(webcam.LEFT_EAR, .62), (webcam.RIGHT_EAR, .38)]:
        points = [(cx-.055,.42),(cx-.027,.398),(cx+.027,.398),(cx+.055,.42),(cx+.027,.442),(cx-.027,.442)]
        for index, (x, y) in zip(indices, points): landmarks[index] = SimpleNamespace(x=x, y=y, z=0)
    place(webcam.LEFT_IRIS, .62, .42, .012, .012)
    place(webcam.RIGHT_IRIS, .38, .42, .012, .012)
    categories = [SimpleNamespace(category_name="eyeBlinkLeft", score=.05), SimpleNamespace(category_name="eyeBlinkRight", score=.05)]
    return SimpleNamespace(face_landmarks=[landmarks], face_blendshapes=[categories], facial_transformation_matrixes=[np.eye(4)])


def test_real_frame_pipeline_reports_face_both_eyes_and_timestamp():
    tracker = WebcamEyeTracker()
    tracker._landmarker.close()
    tracker._landmarker = FakeLandmarker(landmark_result())
    frame = np.random.default_rng(5).integers(60, 195, (480, 640, 3), dtype=np.uint8)
    tracker._cap = FakeCapture(True, frame)
    tracker._connected = True
    tracker._streaming = True
    tracker._backend_name = "TEST"
    sample = tracker.get_sample()
    status = tracker.status()
    assert sample.timestamp_ns > 0
    assert sample.tracker_time_ns > 0
    assert sample.left_gaze_x is not None
    assert sample.right_gaze_x is not None
    assert sample.valid
    assert sample.binocular_valid
    assert sample.left_eye_openness == "OPEN"
    assert sample.right_eye_openness == "OPEN"
    assert sample.left_eye_quality >= .7 and sample.right_eye_quality >= .7
    assert status.camera_open
    assert status.frame_read_success
    assert status.face_detected
    assert status.left_eye_detected and status.right_eye_detected
    assert status.confidence > 0
    assert status.quality_explanation
    tracker.disconnect()


def test_three_frame_read_failures_raise_specific_error():
    tracker = WebcamEyeTracker()
    tracker._cap = FakeCapture(True, None)
    tracker._connected = True
    tracker._streaming = True
    tracker._backend_name = "TEST"
    assert tracker.get_sample() is None
    assert tracker.get_sample() is None
    with pytest.raises(webcam.CameraFrameReadError, match="three consecutive frames"):
        tracker.get_sample()
