from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable

import numpy as np


class EyeOpenness(StrEnum):
    OPEN = "OPEN"
    SQUINTING = "SQUINTING"
    CLOSED = "CLOSED"
    UNCERTAIN = "UNCERTAIN"


class DistanceQuality(StrEnum):
    TOO_FAR = "TOO FAR"
    ACCEPTABLE = "ACCEPTABLE"
    IDEAL = "IDEAL"
    TOO_CLOSE = "TOO CLOSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    """Documented image-space thresholds; eye-size preferences are explicit pixels."""

    minimum_binocular_quality: float = 0.70
    minimum_eye_quality: float | None = None
    ear_closed: float = 0.16
    ear_open: float = 0.23
    blink_squint: float = 0.35
    blink_closed: float = 0.70
    eye_width_min_px: float = 28.0
    preferred_eye_width_min_px: float = 40.0
    preferred_eye_width_max_px: float = 75.0
    eye_width_too_close_px: float = 105.0
    face_width_too_far_ratio: float = 0.24
    face_width_ideal_min_ratio: float = 0.32
    face_width_ideal_max_ratio: float = 0.66
    face_width_too_close_ratio: float = 0.82
    sharpness_low: float = 35.0
    sharpness_good: float = 85.0
    brightness_dark: float = 50.0
    brightness_good_min: float = 70.0
    brightness_good_max: float = 205.0
    brightness_bright: float = 225.0
    max_abs_yaw_deg: float = 25.0
    max_abs_pitch_deg: float = 20.0
    max_abs_roll_deg: float = 20.0
    rolling_window_s: float = 0.75


@dataclass(slots=True)
class EyeEvidence:
    detected: bool = False
    ear: float | None = None
    blink_score: float | None = None
    pixel_width: float = 0.0
    pixel_height: float = 0.0
    sharpness: float = 0.0
    brightness: float = 0.0
    clipped_dark_fraction: float = 0.0
    clipped_bright_fraction: float = 0.0
    edge_safe: bool = False
    geometry_reasonable: bool = False


@dataclass(slots=True)
class EyeQuality:
    score: float
    valid: bool
    openness: EyeOpenness
    size_state: str
    sharpness_state: str
    lighting_state: str
    stability: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MeasurementQuality:
    left: EyeQuality
    right: EyeQuality
    overall: float
    binocular_valid: bool
    head_pose_valid: bool
    head_pose_state: str
    distance_quality: DistanceQuality
    face_quality: float
    guidance: str
    temporal_stability: float


def euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def eye_aspect_ratio(points: Iterable[tuple[float, float]]) -> float | None:
    """Soukupová/Čech EAR: (||p2-p6|| + ||p3-p5||) / (2||p1-p4||)."""
    p = list(points)
    if len(p) != 6:
        raise ValueError("EAR requires six ordered eyelid landmarks")
    horizontal = euclidean(p[0], p[3])
    if horizontal <= 1e-6:
        return None
    return (euclidean(p[1], p[5]) + euclidean(p[2], p[4])) / (2.0 * horizontal)


def classify_openness(ear: float | None, blink_score: float | None, thresholds: QualityThresholds) -> EyeOpenness:
    """Use MediaPipe blink output when present and EAR as an independent fallback/cross-check."""
    if ear is None and blink_score is None:
        return EyeOpenness.UNCERTAIN
    blink = max(0.0, min(1.0, blink_score)) if blink_score is not None else None
    if blink is not None and blink >= thresholds.blink_closed:
        return EyeOpenness.CLOSED
    if ear is not None and ear < thresholds.ear_closed:
        return EyeOpenness.CLOSED
    if (blink is not None and blink >= thresholds.blink_squint) or (ear is not None and ear < thresholds.ear_open):
        return EyeOpenness.SQUINTING
    return EyeOpenness.OPEN


def distance_quality(eye_width_px: float | None, thresholds: QualityThresholds) -> DistanceQuality:
    """Classify image-space distance from measured eye width, never pretend it is centimeters."""
    if eye_width_px is None or eye_width_px <= 0:
        return DistanceQuality.UNKNOWN
    if eye_width_px < thresholds.preferred_eye_width_min_px:
        return DistanceQuality.TOO_FAR
    if eye_width_px <= thresholds.preferred_eye_width_max_px:
        return DistanceQuality.IDEAL
    return DistanceQuality.TOO_CLOSE


def _ramp(value: float, low: float, good: float) -> float:
    if value <= low:
        return 0.0
    if value >= good:
        return 1.0
    return (value - low) / (good - low)


def _eye_size_score(pixel_width: float, thresholds: QualityThresholds) -> tuple[float, str]:
    if pixel_width < thresholds.eye_width_min_px:
        return max(0.0, pixel_width / thresholds.eye_width_min_px * .35), "LOW"
    if pixel_width < thresholds.preferred_eye_width_min_px:
        return .35 + .65 * _ramp(pixel_width, thresholds.eye_width_min_px, thresholds.preferred_eye_width_min_px), "ACCEPTABLE"
    if pixel_width <= thresholds.preferred_eye_width_max_px:
        return 1.0, "GOOD"
    if pixel_width < thresholds.eye_width_too_close_px:
        return .7, "LARGE"
    return .3, "TOO LARGE"


def _lighting_score(eye: EyeEvidence, thresholds: QualityThresholds) -> tuple[float, str]:
    if eye.brightness < thresholds.brightness_dark or eye.clipped_dark_fraction > .45:
        return .15, "TOO DARK"
    if eye.brightness > thresholds.brightness_bright or eye.clipped_bright_fraction > .35:
        return .2, "OVEREXPOSED"
    if thresholds.brightness_good_min <= eye.brightness <= thresholds.brightness_good_max:
        return 1.0, "GOOD"
    return .65, "ACCEPTABLE"


def score_eye(
    evidence: EyeEvidence,
    frame_width: int,
    stability: float,
    thresholds: QualityThresholds,
) -> EyeQuality:
    openness = classify_openness(evidence.ear, evidence.blink_score, thresholds)
    if not evidence.detected:
        return EyeQuality(0.0, False, EyeOpenness.UNCERTAIN, "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", stability, ["eye landmarks not detected"])
    size_score, size_state = _eye_size_score(evidence.pixel_width, thresholds)
    # At sub-threshold resolution, the eyelid/blink estimate is not trustworthy
    # enough to distinguish a true closure from landmark collapse.
    if evidence.pixel_width < thresholds.eye_width_min_px:
        openness = EyeOpenness.UNCERTAIN
    sharp_score = _ramp(evidence.sharpness, thresholds.sharpness_low, thresholds.sharpness_good)
    sharp_state = "GOOD" if evidence.sharpness >= thresholds.sharpness_good else "LOW" if evidence.sharpness <= thresholds.sharpness_low else "ACCEPTABLE"
    lighting_score, lighting_state = _lighting_score(evidence, thresholds)
    openness_score = {EyeOpenness.OPEN: 1.0, EyeOpenness.SQUINTING: .35, EyeOpenness.CLOSED: 0.0, EyeOpenness.UNCERTAIN: .2}[openness]
    geometry_score = 1.0 if evidence.geometry_reasonable and evidence.edge_safe else .25
    raw = 100.0 * (
        .34 * openness_score + .18 * size_score + .16 * sharp_score +
        .14 * lighting_score + .10 * geometry_score + .08 * max(0.0, min(1.0, stability))
    )
    if openness == EyeOpenness.CLOSED:
        raw = min(raw, 12.0)
    elif openness == EyeOpenness.SQUINTING:
        raw = min(raw, 55.0)
    elif openness == EyeOpenness.UNCERTAIN:
        raw = min(raw, 35.0)
    if sharp_score < .25:
        raw = min(raw, 60.0)
    if lighting_score < .5:
        raw = min(raw, 60.0)
    reasons: list[str] = []
    if openness != EyeOpenness.OPEN: reasons.append(f"openness {openness.value.lower()}")
    if size_score < .65: reasons.append("insufficient eye resolution")
    if sharp_score < .5: reasons.append("eye region blurred")
    if lighting_score < .5: reasons.append(lighting_state.lower())
    if not evidence.edge_safe: reasons.append("eye near frame edge")
    if not evidence.geometry_reasonable: reasons.append("landmark geometry uncertain")
    score = max(0.0, min(100.0, raw))
    eye_threshold = thresholds.minimum_eye_quality if thresholds.minimum_eye_quality is not None else thresholds.minimum_binocular_quality
    valid = score >= eye_threshold * 100 and openness == EyeOpenness.OPEN
    return EyeQuality(score, valid, openness, size_state, sharp_state, lighting_state, stability, reasons)


def compose_quality(
    left_evidence: EyeEvidence,
    right_evidence: EyeEvidence,
    frame_width: int,
    face_width_ratio: float | None,
    face_cropped: bool,
    pose_deg: tuple[float | None, float | None, float | None],
    left_stability: float,
    right_stability: float,
    thresholds: QualityThresholds,
) -> MeasurementQuality:
    left = score_eye(left_evidence, frame_width, left_stability, thresholds)
    right = score_eye(right_evidence, frame_width, right_stability, thresholds)
    yaw, pitch, roll = pose_deg
    pose_known = all(value is not None and math.isfinite(value) for value in pose_deg)
    head_valid = bool(pose_known and abs(yaw) <= thresholds.max_abs_yaw_deg and abs(pitch) <= thresholds.max_abs_pitch_deg and abs(roll) <= thresholds.max_abs_roll_deg)
    pose_factor = 1.0 if head_valid else .55 if pose_known else .75
    detected_widths = [eye.pixel_width for eye in (left_evidence, right_evidence) if eye.detected and eye.pixel_width > 0]
    distance = distance_quality(sum(detected_widths) / len(detected_widths) if detected_widths else None, thresholds)
    face_quality = 1.0
    if face_cropped or distance == DistanceQuality.TOO_CLOSE: face_quality = .45
    elif distance == DistanceQuality.TOO_FAR: face_quality = .55
    elif distance == DistanceQuality.UNKNOWN: face_quality = 0.0
    stability = min(left_stability, right_stability)
    overall = min(left.score, right.score) * pose_factor * face_quality * (.65 + .35 * stability)
    binocular_valid = left.valid and right.valid and head_valid and face_quality >= .55 and overall >= thresholds.minimum_binocular_quality * 100
    guidance = select_guidance(left, right, distance, face_cropped, head_valid, stability)
    pose_state = "GOOD" if head_valid else "TURN TOWARD CAMERA" if pose_known else "UNCERTAIN"
    return MeasurementQuality(left, right, max(0.0, min(100.0, overall)), binocular_valid, head_valid, pose_state, distance, face_quality * 100, guidance, stability)


def select_guidance(
    left: EyeQuality,
    right: EyeQuality,
    distance: DistanceQuality,
    face_cropped: bool,
    head_pose_valid: bool,
    stability: float,
) -> str:
    if not left.score and not right.score: return "Center your face"
    if face_cropped or distance == DistanceQuality.TOO_CLOSE: return "Move farther back"
    if distance == DistanceQuality.TOO_FAR: return "Move closer"
    if right.openness in {EyeOpenness.CLOSED, EyeOpenness.SQUINTING}: return "Open right eye fully"
    if left.openness in {EyeOpenness.CLOSED, EyeOpenness.SQUINTING}: return "Open left eye fully"
    if left.lighting_state not in {"GOOD", "ACCEPTABLE"} or right.lighting_state not in {"GOOD", "ACCEPTABLE"}: return "Improve lighting"
    if left.sharpness_state == "LOW" or right.sharpness_state == "LOW": return "Hold still and improve focus"
    if not head_pose_valid: return "Turn toward camera"
    if stability < .75: return "Hold still"
    return "Tracking quality good"


class TemporalQualityWindow:
    def __init__(self, window_s: float = .75) -> None:
        self.window_ns = int(window_s * 1e9)
        self._history: deque[tuple[int, bool, bool]] = deque()

    def update(self, timestamp_ns: int, left_detected: bool, right_detected: bool) -> tuple[float, float]:
        self._history.append((timestamp_ns, left_detected, right_detected))
        cutoff = timestamp_ns - self.window_ns
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()
        if not self._history:
            return 0.0, 0.0
        total = len(self._history)
        return sum(item[1] for item in self._history) / total, sum(item[2] for item in self._history) / total
