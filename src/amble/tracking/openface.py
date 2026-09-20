from __future__ import annotations

import csv
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path

from amble.core.domain import EyeSample
from amble.tracking.base import EyeTracker, TrackerStatus


class OpenFaceEyeTracker(EyeTracker):
    """Adapter for OpenFace FeatureExtraction's live webcam CSV stream.

    Set OPENFACE_FEATURE_EXTRACTION to FeatureExtraction.exe (or its platform
    equivalent). Gaze vectors are projected to normalized proxy coordinates;
    a screen calibration remains necessary and they are not clinical angles.
    """

    tracker_type = "openface_gaze"

    def __init__(self, executable: str | Path | None = None) -> None:
        self.executable = Path(executable or os.getenv("OPENFACE_FEATURE_EXTRACTION", ""))
        self.device_id = 0
        self._connected = False
        self._streaming = False
        self._process: subprocess.Popen | None = None
        self._temp = None
        self._csv_path: Path | None = None
        self._handle = None
        self._reader = None
        self._fps = 0.0
        self._last_perf = 0.0
        self._last: EyeSample | None = None

    def connect(self, device_id: int | str | None = None) -> None:
        if not str(self.executable) or not self.executable.is_file():
            raise RuntimeError(
                "OpenFace FeatureExtraction was not found. Set OPENFACE_FEATURE_EXTRACTION "
                "to the executable installed from the official OpenFace project."
            )
        self.device_id = int(device_id or 0)
        self._connected = True

    def disconnect(self) -> None:
        self.stop_stream()
        self._connected = False

    def start_stream(self) -> None:
        if not self._connected:
            self.connect(self.device_id)
        self._temp = tempfile.TemporaryDirectory(prefix="amble_openface_")
        self._csv_path = Path(self._temp.name) / "openface_live.csv"
        command = [
            str(self.executable), "-device", str(self.device_id), "-of", str(self._csv_path),
            "-gaze", "-pose", "-2Dfp", "-q",
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
        self._streaming = True

    def stop_stream(self) -> None:
        self._streaming = False
        if self._handle:
            self._handle.close(); self._handle = None; self._reader = None
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try: self._process.wait(timeout=3)
            except subprocess.TimeoutExpired: self._process.kill()
        self._process = None
        if self._temp:
            self._temp.cleanup(); self._temp = None

    @staticmethod
    def _number(row: dict[str, str], name: str, default: float | None = None) -> float | None:
        try: return float(row[name].strip())
        except (KeyError, TypeError, ValueError): return default

    @staticmethod
    def _project(vx: float | None, vy: float | None, vz: float | None) -> tuple[float | None, float | None]:
        if vx is None or vy is None or vz is None:
            return None, None
        # OpenFace gaze vector → bounded screen-space proxy; calibration should replace this mapping.
        x_angle = math.atan2(vx, -vz)
        y_angle = math.atan2(vy, math.hypot(vx, vz))
        return max(0.0, min(1.0, .5 + x_angle / 1.2)), max(0.0, min(1.0, .5 + y_angle / .9))

    def _row_to_sample(self, row: dict[str, str]) -> EyeSample:
        left = self._project(self._number(row, "gaze_0_x"), self._number(row, "gaze_0_y"), self._number(row, "gaze_0_z"))
        right = self._project(self._number(row, "gaze_1_x"), self._number(row, "gaze_1_y"), self._number(row, "gaze_1_z"))
        confidence = float(self._number(row, "confidence", 0.0) or 0.0)
        success = int(self._number(row, "success", 0.0) or 0.0) == 1
        now = time.perf_counter()
        if self._last_perf:
            instant = 1.0 / max(now - self._last_perf, 1e-6)
            self._fps = instant if not self._fps else .9 * self._fps + .1 * instant
        self._last_perf = now
        def degrees(name: str) -> float | None:
            value = self._number(row, name); return math.degrees(value) if value is not None else None
        lx, ly = left; rx, ry = right
        return EyeSample(
            timestamp_ns=time.time_ns(), tracker_time_ns=time.perf_counter_ns(),
            left_gaze_x=lx, left_gaze_y=ly, right_gaze_x=rx, right_gaze_y=ry,
            binocular_gaze_x=(lx + rx) / 2 if lx is not None and rx is not None else None,
            binocular_gaze_y=(ly + ry) / 2 if ly is not None and ry is not None else None,
            left_confidence=confidence, right_confidence=confidence,
            head_yaw_deg=degrees("pose_Ry"), head_pitch_deg=degrees("pose_Rx"), head_roll_deg=degrees("pose_Rz"),
            head_x_mm=self._number(row, "pose_Tx"), head_y_mm=self._number(row, "pose_Ty"), head_z_mm=self._number(row, "pose_Tz"),
            camera_fps=self._fps, frame_number=int(self._number(row, "frame", 0) or 0),
            valid=success and confidence >= .5 and lx is not None and rx is not None,
            tracker_type=self.tracker_type,
        )

    def get_sample(self) -> EyeSample | None:
        if not self._streaming or self._csv_path is None:
            return None
        if self._process and self._process.poll() not in (None, 0):
            error = self._process.stderr.read().decode(errors="replace") if self._process.stderr else ""
            raise RuntimeError(f"OpenFace stopped unexpectedly: {error[-500:]}")
        if self._handle is None:
            if not self._csv_path.exists() or self._csv_path.stat().st_size == 0:
                return None
            self._handle = self._csv_path.open("r", newline="", encoding="utf-8-sig")
            self._reader = csv.DictReader(self._handle, skipinitialspace=True)
        latest = None
        while True:
            try: row = next(self._reader)
            except StopIteration: break
            if row: latest = row
        if latest:
            self._last = self._row_to_sample(latest)
        return self._last if latest else None

    def status(self) -> TrackerStatus:
        confidence = min(self._last.left_confidence, self._last.right_confidence) if self._last else 0.0
        return TrackerStatus(
            connected=self._connected, streaming=self._streaming, camera_name=f"OpenFace camera {self.device_id}",
            fps=self._fps, both_eyes_detected=bool(self._last and self._last.valid), confidence=confidence,
            message="OpenFace gaze-vector projection; calibration required; not a clinical measurement",
        )
