from __future__ import annotations

import json
import os
import time

import numpy as np

from amble.analysis.quality import (
    EyeEvidence, EyeOpenness, MeasurementQuality, QualityThresholds,
    TemporalQualityWindow, compose_quality, eye_aspect_ratio,
)
from amble.core.domain import EyeSample
from amble.tracking.base import EyeTracker, TrackerStatus
from amble.tracking.camera import (
    MODEL_PATH,
    CameraError,
    CameraFrameReadError,
    CameraInfo,
    CameraOpenError,
    CascadeLoadError,
    LandmarkConfigurationError,
    OpenCVConfigurationError,
    OpenCVDiagnostics,
    backend_candidates,
    open_camera,
    validate_environment,
)
from amble.tracking.webcam_helpers import (
    LEFT_EAR,
    LEFT_EYE_OUTLINE,
    LEFT_IRIS,
    RIGHT_EAR,
    RIGHT_EYE_OUTLINE,
    RIGHT_IRIS,
    blendshape_map,
    crop_evidence,
    landmark_points,
    pose,
)

os.environ.setdefault("MEDIAPIPE_DISABLE_TELEMETRY", "1")
os.environ.setdefault("GLOG_minloglevel", "2")

try:
    import cv2
except (ImportError, OSError) as exc:
    cv2 = None
    _CV2_IMPORT_ERROR = exc
else:
    _CV2_IMPORT_ERROR = None

try:
    import mediapipe as mp
except (ImportError, OSError) as exc:
    mp = None
    _MEDIAPIPE_IMPORT_ERROR = exc
else:
    _MEDIAPIPE_IMPORT_ERROR = None


def validate_opencv() -> OpenCVDiagnostics:
    return validate_environment(
        cv2,
        mp,
        MODEL_PATH,
        _CV2_IMPORT_ERROR,
        _MEDIAPIPE_IMPORT_ERROR,
    )


def _backend_candidates() -> list[tuple[str, int]]:
    return backend_candidates(cv2)


def _open_camera(index: int):
    validate_opencv()
    return open_camera(cv2, index, _backend_candidates())


def enumerate_cameras(max_devices: int = 4) -> list[CameraInfo]:
    validate_opencv(); found: list[CameraInfo] = []
    for index in range(max_devices):
        try: cap, backend, frame = _open_camera(index)
        except CameraOpenError: continue
        height, width = frame.shape[:2]
        found.append(CameraInfo(index, f"Camera {index}", backend, (width, height), True)); cap.release()
    return found


def _landmark_points(landmarks, indices: tuple[int, ...], width: int, height: int) -> list[tuple[float, float]]:
    return landmark_points(landmarks, indices, width, height)


def _crop_evidence(gray: np.ndarray, points: list[tuple[float, float]], ear: float | None, blink: float | None) -> EyeEvidence:
    return crop_evidence(cv2, gray, points, ear, blink)


def _blendshape_map(result) -> dict[str, float]:
    return blendshape_map(result)


def _pose(result) -> tuple[float | None, float | None, float | None]:
    return pose(cv2, result)


class WebcamEyeTracker(EyeTracker):
    """Real webcam acquisition with MediaPipe landmarks and explainable sample quality."""

    tracker_type = "webcam_mediapipe_proxy"

    def __init__(self, thresholds: QualityThresholds | None = None) -> None:
        validate_opencv()
        self.thresholds = thresholds or QualityThresholds()
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=.55,
            min_face_presence_confidence=.55,
            min_tracking_confidence=.55,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        self._temporal = TemporalQualityWindow(self.thresholds.rolling_window_s)
        self._cap = None; self._connected = False; self._streaming = False; self._camera_index = 0
        self._backend_name = ""; self._frame_number = 0; self._last_frame = None; self._prefetched_frame = None
        self._last_sample: EyeSample | None = None; self._quality: MeasurementQuality | None = None
        self._left_evidence = EyeEvidence(); self._right_evidence = EyeEvidence()
        self._fps = 0.0; self._last_t = 0.0; self._last_mp_ms = 0; self._head_comp = True
        self._debug_overlay = True; self._frame_read_success = False; self._face_detected = False
        self._eye_count = 0; self._consecutive_read_failures = 0

    def connect(self, device_id: int | str | None = None) -> None:
        index = self._camera_index if device_id is None else int(device_id); self.disconnect()
        cap, backend, first_frame = _open_camera(index)
        self._cap, self._camera_index, self._backend_name = cap, index, backend
        self._prefetched_frame, self._frame_read_success, self._connected = first_frame, True, True

    def disconnect(self) -> None:
        self.stop_stream()
        if self._cap is not None: self._cap.release()
        self._cap = None; self._connected = False; self._frame_read_success = False; self._prefetched_frame = None

    def start_stream(self) -> None:
        if not self._connected: self.connect(None)
        self._streaming = True

    def stop_stream(self) -> None: self._streaming = False
    def set_head_pose_compensation(self, enabled: bool) -> None: self._head_comp = enabled
    def set_debug_overlay(self, enabled: bool) -> None: self._debug_overlay = enabled

    def set_minimum_quality(self, threshold: float) -> None:
        values = {name: getattr(self.thresholds, name) for name in self.thresholds.__dataclass_fields__}
        values["minimum_binocular_quality"] = max(0.0, min(1.0, threshold))
        self.thresholds = QualityThresholds(**values)

    def set_preferred_eye_width_range(self, minimum_px: int, maximum_px: int) -> None:
        minimum = max(20, min(int(minimum_px), 100))
        maximum = max(minimum + 5, min(int(maximum_px), 140))
        values = {name: getattr(self.thresholds, name) for name in self.thresholds.__dataclass_fields__}
        values.update({
            "eye_width_min_px": max(12.0, minimum * .70),
            "preferred_eye_width_min_px": float(minimum),
            "preferred_eye_width_max_px": float(maximum),
            "eye_width_too_close_px": max(float(maximum + 10), maximum * 1.4),
        })
        self.thresholds = QualityThresholds(**values)

    def set_eye_quality(self, threshold: float) -> None:
        from dataclasses import replace
        self.thresholds = replace(self.thresholds, minimum_eye_quality=threshold)

    def request_camera_format(self, resolution: str, fps: int) -> None:
        if self._cap is None:return
        if resolution != 'Device default':
            width,height=map(int,resolution.split('x'))
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,width);self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT,height)
        self._cap.set(cv2.CAP_PROP_FPS,fps)
        self._prefetched_frame=None

    def _next_frame(self):
        if self._prefetched_frame is not None:
            frame, self._prefetched_frame, ok = self._prefetched_frame, None, True
        else: ok, frame = self._cap.read()
        self._frame_read_success = bool(ok and frame is not None and frame.size)
        if not self._frame_read_success:
            self._consecutive_read_failures += 1
            if self._consecutive_read_failures >= 3:
                raise CameraFrameReadError(f"Camera {self._camera_index} ({self._backend_name}) failed to return three consecutive frames")
            return None
        self._consecutive_read_failures = 0
        return frame

    def get_sample(self) -> EyeSample | None:
        if not self._streaming or self._cap is None: return None
        frame = self._next_frame()
        if frame is None: return None
        now_perf = time.perf_counter()
        if self._last_t:
            instantaneous = 1.0 / max(now_perf - self._last_t, 1e-6)
            self._fps = instantaneous if not self._fps else .9 * self._fps + .1 * instantaneous
        self._last_t = now_perf; self._frame_number += 1
        height, width = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        timestamp_ms = max(self._last_mp_ms + 1, int(now_perf * 1000)); self._last_mp_ms = timestamp_ms
        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
        landmarks = result.face_landmarks[0] if result.face_landmarks else None
        self._face_detected = landmarks is not None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        left_evidence, right_evidence = EyeEvidence(), EyeEvidence()
        left_center = right_center = (None, None)
        face_box = None; face_ratio = None; face_cropped = False
        yaw = pitch = roll = None
        if landmarks:
            all_x = np.array([item.x * width for item in landmarks]); all_y = np.array([item.y * height for item in landmarks])
            fx1, fy1, fx2, fy2 = int(all_x.min()), int(all_y.min()), int(all_x.max()), int(all_y.max())
            face_box = (fx1, fy1, fx2, fy2); face_ratio = (fx2 - fx1) / max(width, 1)
            face_cropped = fx1 <= width * .015 or fy1 <= height * .015 or fx2 >= width * .985 or fy2 >= height * .985
            blend = _blendshape_map(result)
            left_outline = _landmark_points(landmarks, LEFT_EYE_OUTLINE, width, height)
            right_outline = _landmark_points(landmarks, RIGHT_EYE_OUTLINE, width, height)
            left_ear = eye_aspect_ratio(_landmark_points(landmarks, LEFT_EAR, width, height))
            right_ear = eye_aspect_ratio(_landmark_points(landmarks, RIGHT_EAR, width, height))
            left_evidence = _crop_evidence(gray, left_outline, left_ear, blend.get("eyeBlinkLeft"))
            right_evidence = _crop_evidence(gray, right_outline, right_ear, blend.get("eyeBlinkRight"))
            left_iris = _landmark_points(landmarks, LEFT_IRIS, width, height)
            right_iris = _landmark_points(landmarks, RIGHT_IRIS, width, height)
            if left_iris: left_center = (float(np.mean([p[0] for p in left_iris])) / width, float(np.mean([p[1] for p in left_iris])) / height)
            if right_iris: right_center = (float(np.mean([p[0] for p in right_iris])) / width, float(np.mean([p[1] for p in right_iris])) / height)
            yaw, pitch, roll = _pose(result)
        left_stability, right_stability = self._temporal.update(time.time_ns(), left_evidence.detected, right_evidence.detected)
        quality = compose_quality(left_evidence, right_evidence, width, face_ratio, face_cropped, (yaw, pitch, roll), left_stability, right_stability, self.thresholds)
        self._left_evidence, self._right_evidence = left_evidence, right_evidence
        self._quality = quality; self._eye_count = int(left_evidence.detected) + int(right_evidence.detected)
        lx, ly = left_center; rx, ry = right_center
        bx = (lx + rx) / 2 if lx is not None and rx is not None else None
        by = (ly + ry) / 2 if ly is not None and ry is not None else None
        if self._debug_overlay: self._draw_overlay(frame, landmarks, face_box, left_center, right_center, quality)
        self._last_frame = frame
        reasons = {"left": quality.left.reasons, "right": quality.right.reasons, "guidance": quality.guidance}
        lighting = "GOOD" if quality.left.lighting_state == quality.right.lighting_state == "GOOD" else f"L:{quality.left.lighting_state} R:{quality.right.lighting_state}"
        self._last_sample = EyeSample(
            timestamp_ns=time.time_ns(), tracker_time_ns=time.perf_counter_ns(),
            left_gaze_x=lx, left_gaze_y=ly, right_gaze_x=rx, right_gaze_y=ry,
            binocular_gaze_x=bx, binocular_gaze_y=by,
            left_pupil_x=lx, left_pupil_y=ly, right_pupil_x=rx, right_pupil_y=ry,
            left_confidence=quality.left.score / 100, right_confidence=quality.right.score / 100,
            head_yaw_deg=yaw, head_pitch_deg=pitch, head_roll_deg=roll,
            camera_fps=self._fps, frame_number=self._frame_number,
            valid=quality.binocular_valid, tracker_type=self.tracker_type,
            left_eye_valid=quality.left.valid, right_eye_valid=quality.right.valid, binocular_valid=quality.binocular_valid,
            left_eye_quality=quality.left.score / 100, right_eye_quality=quality.right.score / 100, overall_quality=quality.overall / 100,
            left_eye_openness=quality.left.openness.value, right_eye_openness=quality.right.openness.value,
            left_eye_pixel_width=left_evidence.pixel_width, right_eye_pixel_width=right_evidence.pixel_width,
            left_eye_sharpness=left_evidence.sharpness, right_eye_sharpness=right_evidence.sharpness,
            left_eye_lighting=quality.left.lighting_state, right_eye_lighting=quality.right.lighting_state,
            lighting_quality=lighting, head_pose_valid=quality.head_pose_valid, face_quality=quality.face_quality / 100,
            distance_quality=quality.distance_quality.value, tracking_guidance=quality.guidance,
            quality_reasons=json.dumps(reasons, separators=(",", ":")), quality_threshold=self.thresholds.minimum_binocular_quality,
        )
        return self._last_sample

    def _draw_overlay(self, frame, landmarks, face_box, left_center, right_center, quality) -> None:
        if face_box:
            x1, y1, x2, y2 = face_box; cv2.rectangle(frame, (x1, y1), (x2, y2), (110, 150, 190), 1)
        if landmarks:
            height, width = frame.shape[:2]
            for indices, color, label, center in [
                (LEFT_EYE_OUTLINE, (70, 220, 140), "L", left_center),
                (RIGHT_EYE_OUTLINE, (220, 150, 75), "R", right_center),
            ]:
                pts = np.array(_landmark_points(landmarks, indices, width, height), dtype=np.int32)
                if len(pts): cv2.polylines(frame, [pts], True, color, 1, cv2.LINE_AA)
                if center[0] is not None:
                    cx, cy = int(center[0] * width), int(center[1] * height)
                    cv2.circle(frame, (cx, cy), 5, color, 2, cv2.LINE_AA); cv2.drawMarker(frame, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 7, 1)
                    cv2.putText(frame, label, (cx + 7, cy - 5), cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1, cv2.LINE_AA)
        color = (70, 220, 140) if quality.binocular_valid else (70, 90, 235)
        cv2.putText(frame, f"L {quality.left.score:.0f}% {quality.left.openness.value} | R {quality.right.score:.0f}% {quality.right.openness.value}", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, .54, color, 2, cv2.LINE_AA)
        cv2.putText(frame, quality.guidance, (12, 48), cv2.FONT_HERSHEY_SIMPLEX, .52, color, 2, cv2.LINE_AA)

    def get_preview_frame(self): return self._last_frame

    def status(self) -> TrackerStatus:
        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self._cap is not None else 0
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if self._cap is not None else 0
        q = self._quality
        if not self._connected: message = "Webcam disconnected"
        elif q and q.binocular_valid: message = "VALID BINOCULAR SAMPLE"
        elif q: message = f"INVALID — {q.guidance.upper()}"
        else: message = "Camera open; waiting for landmark measurement"
        explanation = ""
        if q:
            explanation = (
                f"Left: detected={'yes' if self._eye_count >= 1 else 'no'}, openness={q.left.openness.value}, size={q.left.size_state}, "
                f"EAR={self._left_evidence.ear if self._left_evidence.ear is not None else 'n/a'}, blink={self._left_evidence.blink_score if self._left_evidence.blink_score is not None else 'n/a'}, sharpness={q.left.sharpness_state}, lighting={q.left.lighting_state}, stability={q.left.stability:.0%}\n"
                f"Right: detected={'yes' if self._eye_count >= 2 else 'no'}, openness={q.right.openness.value}, size={q.right.size_state}, "
                f"EAR={self._right_evidence.ear if self._right_evidence.ear is not None else 'n/a'}, blink={self._right_evidence.blink_score if self._right_evidence.blink_score is not None else 'n/a'}, sharpness={q.right.sharpness_state}, lighting={q.right.lighting_state}, stability={q.right.stability:.0%}\n"
                f"Head pose={q.head_pose_state}; distance={q.distance_quality.value}; "
                f"preferred eye width={self.thresholds.preferred_eye_width_min_px:.0f}–{self.thresholds.preferred_eye_width_max_px:.0f}px; overall={q.overall:.0f}%"
            )
        return TrackerStatus(
            connected=self._connected, streaming=self._streaming, camera_name=f"Camera {self._camera_index}",
            resolution=(width, height), fps=self._fps, both_eyes_detected=self._eye_count >= 2,
            confidence=q.overall / 100 if q else 0.0, message=message, backend=self._backend_name,
            camera_index=self._camera_index, camera_open=bool(self._cap is not None and self._cap.isOpened()),
            frame_read_success=self._frame_read_success, face_detected=self._face_detected,
            left_eye_detected=self._eye_count >= 1, right_eye_detected=self._eye_count >= 2,
            left_eye_quality=q.left.score / 100 if q else 0.0, right_eye_quality=q.right.score / 100 if q else 0.0,
            overall_quality=q.overall / 100 if q else 0.0,
            left_eye_openness=q.left.openness.value if q else EyeOpenness.UNCERTAIN.value,
            right_eye_openness=q.right.openness.value if q else EyeOpenness.UNCERTAIN.value,
            left_eye_pixel_width=self._last_sample.left_eye_pixel_width if self._last_sample else 0.0,
            right_eye_pixel_width=self._last_sample.right_eye_pixel_width if self._last_sample else 0.0,
            left_eye_sharpness=self._last_sample.left_eye_sharpness if self._last_sample else 0.0,
            right_eye_sharpness=self._last_sample.right_eye_sharpness if self._last_sample else 0.0,
            lighting_quality=self._last_sample.lighting_quality if self._last_sample else "UNAVAILABLE",
            head_pose_state=q.head_pose_state if q else "UNCERTAIN", head_yaw_deg=self._last_sample.head_yaw_deg if self._last_sample else None,
            head_pitch_deg=self._last_sample.head_pitch_deg if self._last_sample else None, head_roll_deg=self._last_sample.head_roll_deg if self._last_sample else None,
            distance_quality=q.distance_quality.value if q else "UNKNOWN", binocular_valid=q.binocular_valid if q else False,
            guidance=q.guidance if q else "Center your face", quality_explanation=explanation,
        )

    def __del__(self):
        try: self._landmarker.close()
        except Exception: pass
