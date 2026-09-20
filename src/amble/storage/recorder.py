"""Append-only session recording and finalization."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from amble.core.domain import RAW_COLUMNS, EyeSample
from amble.storage.store import utc_now

if TYPE_CHECKING:
    from amble.storage.store import DataStore

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


class SessionRecorder:
    """Append raw samples immediately; preserve row identity at close."""

    def __init__(
        self,
        store: DataStore,
        session_id: str,
        session_dir: Path,
        video_enabled: bool = False,
    ) -> None:
        self.store = store
        self.session_id = session_id
        self.session_dir = session_dir
        self.csv_path = session_dir / "raw_eye_tracking.csv"
        self.events_path = session_dir / "events.csv"
        self._file = self.csv_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file, fieldnames=RAW_COLUMNS, extrasaction="ignore"
        )
        self._writer.writeheader()
        self._events = self.events_path.open("w", newline="", encoding="utf-8")
        self._event_writer = csv.DictWriter(
            self._events,
            fieldnames=["timestamp_ns", "event", "phase", "payload_json"],
        )
        self._event_writer.writeheader()
        self.sample_count = 0
        self.valid_count = 0
        self.closed = False
        self.video_enabled = video_enabled
        self._video_writer = None

    def append(self, sample: EyeSample) -> None:
        if self.closed:
            raise RuntimeError("Recorder is closed")
        sample.session_id = self.session_id
        self._writer.writerow(sample.to_record())
        self.sample_count += 1
        self.valid_count += int(sample.valid)
        if self.sample_count % 30 == 0:
            self._file.flush()

    def event(
        self,
        timestamp_ns: int,
        event: str,
        phase: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._event_writer.writerow(
            {
                "timestamp_ns": timestamp_ns,
                "event": event,
                "phase": phase,
                "payload_json": json.dumps(payload or {}, separators=(",", ":")),
            }
        )
        self._events.flush()

    def append_video_frame(self, frame, fps: float = 30.0) -> None:
        """Record frames only after the researcher explicitly opts in."""
        if not self.video_enabled or cv2 is None or frame is None:
            return
        if self._video_writer is None:
            height, width = frame.shape[:2]
            codec = cv2.VideoWriter_fourcc(*"mp4v")
            self._video_writer = cv2.VideoWriter(
                str(self.session_dir / "camera_video.mp4"),
                codec,
                max(1.0, float(fps)),
                (width, height),
            )
            if not self._video_writer.isOpened():
                self._video_writer.release()
                self._video_writer = None
                raise RuntimeError("Camera video file could not be opened for recording")
        self._video_writer.write(frame)

    def close(self, state: str = "complete") -> Path:
        if state not in {"complete", "aborted"}:
            raise ValueError("Invalid final session state")
        if self.closed:
            return self.session_dir
        self._file.flush()
        self._file.close()
        self._events.flush()
        self._events.close()
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
        parquet_written = False
        if pd is not None:
            try:
                frame = pd.read_csv(self.csv_path)
                frame.to_parquet(
                    self.session_dir / "raw_eye_tracking.parquet", index=False
                )
                parquet_written = True
            except (ImportError, ValueError):
                parquet_written = False
        with self.store._connect() as conn:
            conn.execute(
                """UPDATE sessions SET ended_at=?, state=?, sample_count=?,
                   valid_sample_count=? WHERE session_id=?""",
                (
                    utc_now(),
                    state,
                    self.sample_count,
                    self.valid_count,
                    self.session_id,
                ),
            )
        metadata_path = self.session_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["ended_at"] = utc_now()
        metadata["state"] = state
        metadata["sample_count"] = self.sample_count
        metadata["valid_sample_count"] = self.valid_count
        metadata["formats"] = {
            "raw_csv": True,
            "raw_parquet": parquet_written,
            "camera_video": bool(
                self.video_enabled
                and (self.session_dir / "camera_video.mp4").exists()
            ),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self.closed = True
        return self.session_dir


__all__ = ["SessionRecorder"]
