from __future__ import annotations

import math
import random
import time

from amble.core.domain import EyeSample
from amble.tracking.base import EyeTracker, TrackerStatus


class SimulatedEyeTracker(EyeTracker):
    """Deterministic-enough research workflow simulator, never clinical data."""

    tracker_type = "simulated"

    def __init__(self, sample_rate_hz: float = 60.0, seed: int = 7) -> None:
        self.sample_rate_hz = sample_rate_hz
        self._rng = random.Random(seed)
        self._connected = False
        self._streaming = False
        self._frame = 0
        self._last_ns = 0
        self._target = (0.5, 0.5)
        self._gaze = [0.5, 0.5]
        self._quality_threshold = 0.70
        self._eye_threshold = 0.70

    def connect(self, device_id: int | str | None = None) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self.stop_stream()
        self._connected = False

    def start_stream(self) -> None:
        if not self._connected:
            self.connect()
        self._streaming = True
        self._last_ns = 0

    def stop_stream(self) -> None:
        self._streaming = False

    def set_target(self, x: float, y: float) -> None:
        self._target = (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))

    def set_minimum_quality(self, threshold: float) -> None:
        self._quality_threshold = max(0.0, min(1.0, threshold))

    def set_eye_quality(self, threshold: float) -> None:
        self._eye_threshold=threshold

    def get_sample(self) -> EyeSample | None:
        if not self._streaming:
            return None
        now = time.perf_counter_ns()
        interval = int(1e9 / self.sample_rate_hz)
        if self._last_ns and now - self._last_ns < interval:
            return None
        self._last_ns = now
        self._frame += 1
        # First-order lag plus realistic noise and a small binocular disparity.
        alpha = 0.28
        self._gaze[0] += alpha * (self._target[0] - self._gaze[0])
        self._gaze[1] += alpha * (self._target[1] - self._gaze[1])
        phase = self._frame / self.sample_rate_hz
        disparity = 0.006 + 0.002 * math.sin(phase * 1.7)
        noise_l = (self._rng.gauss(0, 0.006), self._rng.gauss(0, 0.006))
        noise_r = (self._rng.gauss(0, 0.006), self._rng.gauss(0, 0.006))
        lx = self._gaze[0] - disparity / 2 + noise_l[0]
        ly = self._gaze[1] + noise_l[1]
        rx = self._gaze[0] + disparity / 2 + noise_r[0]
        ry = self._gaze[1] + noise_r[1]
        confidence = max(0.0, min(1.0, 0.95 + self._rng.gauss(0, 0.025)))
        timestamp = time.time_ns()
        return EyeSample(
            timestamp_ns=timestamp,
            tracker_time_ns=now,
            left_gaze_x=lx, left_gaze_y=ly,
            right_gaze_x=rx, right_gaze_y=ry,
            binocular_gaze_x=(lx + rx) / 2, binocular_gaze_y=(ly + ry) / 2,
            left_pupil_x=lx, left_pupil_y=ly,
            right_pupil_x=rx, right_pupil_y=ry,
            left_pupil_diameter=3.2 + self._rng.gauss(0, 0.04),
            right_pupil_diameter=3.15 + self._rng.gauss(0, 0.04),
            left_confidence=confidence, right_confidence=confidence,
            head_yaw_deg=1.2 * math.sin(phase / 2),
            head_pitch_deg=0.8 * math.sin(phase / 3),
            head_roll_deg=0.3 * math.cos(phase / 4),
            camera_fps=self.sample_rate_hz, frame_number=self._frame,
            valid=confidence >= max(self._quality_threshold,self._eye_threshold), tracker_type=self.tracker_type,
            left_eye_valid=confidence >= self._eye_threshold,
            right_eye_valid=confidence >= self._eye_threshold,
            binocular_valid=confidence >= max(self._quality_threshold,self._eye_threshold),
            left_eye_quality=confidence, right_eye_quality=confidence, overall_quality=confidence,
            left_eye_openness="OPEN", right_eye_openness="OPEN",
            left_eye_pixel_width=64.0, right_eye_pixel_width=64.0,
            left_eye_sharpness=120.0, right_eye_sharpness=120.0,
            left_eye_lighting="GOOD", right_eye_lighting="GOOD", lighting_quality="GOOD",
            head_pose_valid=True, face_quality=.95, distance_quality="IDEAL",
            tracking_guidance="Tracking quality good", quality_threshold=self._quality_threshold,
        )

    def status(self) -> TrackerStatus:
        return TrackerStatus(
            connected=self._connected, streaming=self._streaming,
            camera_name="Synthetic research source", resolution=(1280, 720),
            fps=self.sample_rate_hz, both_eyes_detected=True, confidence=0.95,
            message="SIMULATED DATA — not a camera measurement",
            backend="Simulator", camera_open=False, frame_read_success=False,
            face_detected=True, left_eye_detected=True, right_eye_detected=True,
            left_eye_quality=.95, right_eye_quality=.95, overall_quality=.95,
            left_eye_openness="OPEN", right_eye_openness="OPEN",
            left_eye_pixel_width=64, right_eye_pixel_width=64,
            left_eye_sharpness=120, right_eye_sharpness=120, lighting_quality="GOOD",
            head_pose_state="GOOD", head_yaw_deg=0, head_pitch_deg=0, head_roll_deg=0,
            distance_quality="IDEAL", binocular_valid=True, guidance="Synthetic data",
            quality_explanation="Simulator quality is synthetic and not a camera measurement.",
        )
