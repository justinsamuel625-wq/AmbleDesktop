"""Camera discovery and OpenCV/MediaPipe environment diagnostics."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


class CameraError(RuntimeError):
    """Base class for explicit acquisition failures shown in the Hardware UI."""


class OpenCVConfigurationError(CameraError):
    pass


class LandmarkConfigurationError(CameraError):
    pass


class CascadeLoadError(CameraError):
    pass


class CameraOpenError(CameraError):
    pass


class CameraFrameReadError(CameraError):
    pass


@dataclass(frozen=True, slots=True)
class OpenCVDiagnostics:
    python_executable: str
    module_path: str
    version: str
    cascade_classifier_available: bool
    video_capture_available: bool
    haar_root: str
    face_cascade_loaded: bool
    eye_cascade_loaded: bool
    landmark_backend: str
    landmark_model_path: str


@dataclass(frozen=True, slots=True)
class CameraInfo:
    index: int
    name: str
    backend: str
    resolution: tuple[int, int]
    frame_read_success: bool


MODEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "face_landmarker.task"


def validate_environment(
    cv2_module,
    mediapipe_module,
    model_path: Path = MODEL_PATH,
    cv2_import_error: Exception | None = None,
    mediapipe_import_error: Exception | None = None,
) -> OpenCVDiagnostics:
    """Validate the runtime dependencies used by the webcam tracker."""
    if cv2_module is None:
        detail = f" ({cv2_import_error})" if cv2_import_error else ""
        raise OpenCVConfigurationError(
            "OpenCV could not be imported from the project .venv" + detail
        )
    required = ["CascadeClassifier", "VideoCapture", "cvtColor", "data"]
    missing = [name for name in required if not hasattr(cv2_module, name)]
    if missing:
        raise OpenCVConfigurationError(
            f"Incompatible OpenCV {getattr(cv2_module, '__version__', 'unknown')} at "
            f"{getattr(cv2_module, '__file__', 'unknown')}. Missing required API: "
            f"{', '.join(missing)}. Amble requires opencv-contrib-python>=4.14,<5."
        )
    root = Path(cv2_module.data.haarcascades)
    face_path = root / "haarcascade_frontalface_default.xml"
    eye_path = root / "haarcascade_eye_tree_eyeglasses.xml"
    missing_files = [str(path) for path in (face_path, eye_path) if not path.is_file()]
    if missing_files:
        raise CascadeLoadError(
            "OpenCV Haar cascade file(s) missing: " + ", ".join(missing_files)
        )
    face = cv2_module.CascadeClassifier(str(face_path))
    eyes = cv2_module.CascadeClassifier(str(eye_path))
    if face.empty() or eyes.empty():
        raise CascadeLoadError(f"OpenCV cascade failed to load from {root}")
    if mediapipe_module is None:
        raise LandmarkConfigurationError(
            f"MediaPipe could not be imported: {mediapipe_import_error}"
        )
    if not model_path.is_file():
        raise LandmarkConfigurationError(
            f"MediaPipe Face Landmarker model is missing: {model_path}"
        )
    return OpenCVDiagnostics(
        sys.executable,
        str(Path(cv2_module.__file__).resolve()),
        str(cv2_module.__version__),
        True,
        True,
        str(root.resolve()),
        True,
        True,
        f"MediaPipe Face Landmarker {mediapipe_module.__version__}",
        str(model_path),
    )


def backend_candidates(cv2_module) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    if os.name == "nt":
        candidates.extend(
            [("MSMF", cv2_module.CAP_MSMF), ("DirectShow", cv2_module.CAP_DSHOW)]
        )
    candidates.append(("Auto", cv2_module.CAP_ANY))
    unique: list[tuple[str, int]] = []
    seen: set[int] = set()
    for item in candidates:
        if item[1] not in seen:
            unique.append(item)
            seen.add(item[1])
    return unique


def open_camera(cv2_module, index: int, candidates) -> tuple[object, str, object]:
    failures: list[str] = []
    for backend_name, backend_id in candidates:
        capture = cv2_module.VideoCapture(index, backend_id)
        if not capture.isOpened():
            failures.append(f"{backend_name}: could not open")
            capture.release()
            continue
        ok, frame = capture.read()
        if ok and frame is not None and frame.size:
            actual = (
                capture.getBackendName()
                if hasattr(capture, "getBackendName")
                else backend_name
            )
            return capture, actual, frame
        failures.append(f"{backend_name}: opened but frame read failed")
        capture.release()
    raise CameraOpenError(
        f"Camera index {index} is unavailable "
        f"({'; '.join(failures) or 'no backend available'}). Check Windows camera "
        "privacy, close other camera applications, and scan again."
    )


__all__ = [
    "CameraError",
    "CameraFrameReadError",
    "CameraInfo",
    "CameraOpenError",
    "CascadeLoadError",
    "LandmarkConfigurationError",
    "MODEL_PATH",
    "OpenCVConfigurationError",
    "OpenCVDiagnostics",
    "backend_candidates",
    "open_camera",
    "validate_environment",
]
