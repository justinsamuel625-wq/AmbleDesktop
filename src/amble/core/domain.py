from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import math
import re
from typing import Any


class MetricKind(StrEnum):
    DIRECT = "direct measurement"
    ESTIMATED = "estimated metric"
    PROXY = "proxy metric"


class ExperimentKind(StrEnum):
    FIXATION = "fixation"
    PURSUIT = "smooth_pursuit"
    VERGENCE_PROXY = "vergence_proxy"
    EXTERNAL_NEAR_FAR = "external_near_far"

    @classmethod
    def parse(cls, value: "ExperimentKind | str") -> "ExperimentKind":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError as exc:
            raise ValueError(f"Unsupported experiment type: {value!r}") from exc


class PursuitTrajectory(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    CIRCULAR = "circular"
    SINUSOIDAL = "sinusoidal"

    @classmethod
    def parse(cls, value: "PursuitTrajectory | str") -> "PursuitTrajectory":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError as exc:
            raise ValueError(f"Unsupported pursuit trajectory: {value!r}") from exc


def validate_subject_identifier(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError("Enter a coded subject identifier.")
    if len(clean) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", clean):
        raise ValueError("Subject identifiers must be 1–64 letters, numbers, periods, underscores, or hyphens.")
    return clean


@dataclass(slots=True)
class EyeSample:
    timestamp_ns: int
    session_id: str = ""
    experiment_id: str = ""
    trial_id: str = ""
    target_x: float | None = None
    target_y: float | None = None
    left_gaze_x: float | None = None
    left_gaze_y: float | None = None
    right_gaze_x: float | None = None
    right_gaze_y: float | None = None
    binocular_gaze_x: float | None = None
    binocular_gaze_y: float | None = None
    left_pupil_x: float | None = None
    left_pupil_y: float | None = None
    right_pupil_x: float | None = None
    right_pupil_y: float | None = None
    left_pupil_diameter: float | None = None
    right_pupil_diameter: float | None = None
    left_confidence: float = 0.0
    right_confidence: float = 0.0
    head_yaw_deg: float | None = None
    head_pitch_deg: float | None = None
    head_roll_deg: float | None = None
    head_x_mm: float | None = None
    head_y_mm: float | None = None
    head_z_mm: float | None = None
    camera_fps: float = 0.0
    frame_number: int = 0
    event_marker: str = ""
    experiment_phase: str = ""
    phase_attempt: int = 1
    tracker_time_ns: int | None = None
    valid: bool = False
    tracker_type: str = ""
    target_distance_cm: float | None = None
    left_eye_valid: bool = False
    right_eye_valid: bool = False
    binocular_valid: bool = False
    left_eye_quality: float = 0.0
    right_eye_quality: float = 0.0
    overall_quality: float = 0.0
    left_eye_openness: str = "UNCERTAIN"
    right_eye_openness: str = "UNCERTAIN"
    left_eye_pixel_width: float = 0.0
    right_eye_pixel_width: float = 0.0
    left_eye_sharpness: float = 0.0
    right_eye_sharpness: float = 0.0
    left_eye_lighting: str = "UNAVAILABLE"
    right_eye_lighting: str = "UNAVAILABLE"
    lighting_quality: str = "UNAVAILABLE"
    head_pose_valid: bool = False
    face_quality: float = 0.0
    distance_quality: str = "UNKNOWN"
    tracking_guidance: str = ""
    quality_reasons: str = "{}"
    quality_threshold: float = 0.70

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CalibrationPoint:
    target_x: float
    target_y: float
    left_error_px: float
    right_error_px: float
    binocular_error_px: float
    valid: bool
    samples: int


@dataclass(slots=True)
class CalibrationResult:
    calibration_id: str
    created_at: str
    screen_width_px: int
    screen_height_px: int
    points: list[CalibrationPoint] = field(default_factory=list)
    tracker_type: str = ""

    @property
    def average_error_px(self) -> float | None:
        values = [p.binocular_error_px for p in self.points if p.valid]
        return sum(values) / len(values) if values else None

    @property
    def quality(self) -> str:
        error = self.average_error_px
        if error is None or len([p for p in self.points if p.valid]) < 7:
            return "failed"
        if error <= 60:
            return "good"
        if error <= 120:
            return "acceptable"
        return "poor"


@dataclass(slots=True)
class ExperimentConfig:
    name: str
    kind: ExperimentKind
    duration_s: float = 10.0
    trials: int = 1
    trajectory: PursuitTrajectory = PursuitTrajectory.HORIZONTAL
    speed_hz: float = 0.2
    amplitude: float = 0.35
    fixation_target_x: float = 0.5
    fixation_target_y: float = 0.5
    target_size_px: int = 5
    phases: list[str] = field(default_factory=lambda: ["pre", "intervention", "post"])
    randomize: bool = False
    quality_threshold: float = 0.70

    def __post_init__(self) -> None:
        self.kind = ExperimentKind.parse(self.kind)
        self.trajectory = PursuitTrajectory.parse(self.trajectory)
        numeric = {
            "duration": self.duration_s, "speed": self.speed_hz, "amplitude": self.amplitude,
            "fixation target X": self.fixation_target_x, "fixation target Y": self.fixation_target_y,
            "quality threshold": self.quality_threshold,
        }
        if not all(math.isfinite(float(value)) for value in numeric.values()):
            raise ValueError("Experiment numeric settings must be finite.")
        if not .1 <= self.duration_s <= 3600:
            raise ValueError("Duration must be between 0.1 and 3600 seconds per phase.")
        if not .02 <= self.speed_hz <= 3:
            raise ValueError("Speed must be between 0.02 and 3 Hz.")
        if not .01 <= self.amplitude <= .45:
            raise ValueError("Amplitude must be between 0.01 and 0.45 normalized screen half-range.")
        if not .05 <= self.fixation_target_x <= .95 or not .05 <= self.fixation_target_y <= .95:
            raise ValueError("Fixation target position must stay within 5–95% of the screen.")
        if not 3 <= self.target_size_px <= 30:
            raise ValueError("Target size must be between 3 and 30 pixels.")
        if not 0 <= self.quality_threshold <= 1:
            raise ValueError("Quality threshold must be between 0 and 1.")
        if not self.phases or any(not str(phase).strip() for phase in self.phases):
            raise ValueError("At least one named experiment phase is required.")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["trajectory"] = self.trajectory.value
        return data


RAW_COLUMNS = list(EyeSample.__dataclass_fields__)
