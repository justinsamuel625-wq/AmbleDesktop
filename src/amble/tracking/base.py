from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from amble.core.domain import EyeSample


@dataclass(slots=True)
class TrackerStatus:
    connected: bool = False
    streaming: bool = False
    camera_name: str = ""
    resolution: tuple[int, int] = (0, 0)
    fps: float = 0.0
    both_eyes_detected: bool = False
    confidence: float = 0.0
    message: str = "Disconnected"
    backend: str = ""
    camera_index: int | None = None
    camera_open: bool = False
    frame_read_success: bool = False
    face_detected: bool = False
    left_eye_detected: bool = False
    right_eye_detected: bool = False
    left_eye_quality: float = 0.0
    right_eye_quality: float = 0.0
    overall_quality: float = 0.0
    left_eye_openness: str = "UNCERTAIN"
    right_eye_openness: str = "UNCERTAIN"
    left_eye_pixel_width: float = 0.0
    right_eye_pixel_width: float = 0.0
    left_eye_sharpness: float = 0.0
    right_eye_sharpness: float = 0.0
    lighting_quality: str = "UNAVAILABLE"
    head_pose_state: str = "UNCERTAIN"
    head_yaw_deg: float | None = None
    head_pitch_deg: float | None = None
    head_roll_deg: float | None = None
    distance_quality: str = "UNKNOWN"
    binocular_valid: bool = False
    guidance: str = ""
    quality_explanation: str = ""


class EyeTracker(ABC):
    """Replaceable acquisition boundary. Coordinates are normalized [0, 1]."""

    tracker_type = "abstract"

    @abstractmethod
    def connect(self, device_id: int | str | None = None) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def start_stream(self) -> None: ...

    @abstractmethod
    def stop_stream(self) -> None: ...

    @abstractmethod
    def get_sample(self) -> EyeSample | None: ...

    @abstractmethod
    def status(self) -> TrackerStatus: ...

    def get_preview_frame(self) -> Any | None:
        return None

    def set_target(self, x: float, y: float) -> None:
        """Optional simulator/testing hook; hardware implementations ignore it."""

    def set_head_pose_compensation(self, enabled: bool) -> None:
        """Optional tracker feature."""

    def set_debug_overlay(self, enabled: bool) -> None:
        """Optional acquisition debugging overlay."""

    def set_minimum_quality(self, threshold: float) -> None:
        """Optional measurement-quality gate expressed as [0, 1]."""

    def set_preferred_eye_width_range(self, minimum_px: int, maximum_px: int) -> None:
        """Optional image-space camera-distance preference in eye-width pixels."""

    def set_eye_quality(self, threshold: float) -> None:
        """Optional independent per-eye quality gate."""


class SensorStream(ABC):
    """Generic future-facing stream boundary for EEG, IMU, HR, VR and LSL."""

    stream_type = "generic"

    @abstractmethod
    def start_stream(self) -> None: ...

    @abstractmethod
    def stop_stream(self) -> None: ...

    @abstractmethod
    def get_sample(self) -> dict[str, Any] | None: ...
