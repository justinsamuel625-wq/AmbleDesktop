from __future__ import annotations

import csv
import json
import platform
import shutil
import sqlite3
import sys
import threading
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from amble import __version__
from amble.domain import CalibrationResult, EyeSample, ExperimentConfig, RAW_COLUMNS, validate_subject_identifier

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class DataStore:
    """SQLite metadata plus append-only CSV acquisition and Parquet finalization."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or Path.home() / "Amble Research Data").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.root / "sessions"
        self.sessions_dir.mkdir(exist_ok=True)
        self.db_path = self.root / "amble.sqlite3"
        self._local = threading.local()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subjects (
                    subject_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
                    created_at TEXT NOT NULL,
                    ended_at TEXT,
                    experiment_kind TEXT NOT NULL,
                    tracker_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    session_dir TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    calibration_json TEXT,
                    software_version TEXT NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    valid_sample_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS metrics (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    phase TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    value REAL,
                    unit TEXT NOT NULL,
                    metric_kind TEXT NOT NULL,
                    quality_ok INTEGER NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(session_id, phase, metric_name)
                );
                CREATE INDEX IF NOT EXISTS ix_sessions_subject ON sessions(subject_id, created_at);
                """
            )

            columns = {row[1] for row in conn.execute('PRAGMA table_info(subjects)')}
            if 'archived' not in columns:
                conn.execute('ALTER TABLE subjects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')

    def ensure_subject(self, subject_id: str, notes: str = "") -> None:
        clean = validate_subject_identifier(subject_id)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO subjects(subject_id, created_at, notes) VALUES (?, ?, ?)",
                (clean, utc_now(), notes),
            )

    def create_session(
        self,
        subject_id: str,
        config: ExperimentConfig,
        tracker_type: str,
        calibration: CalibrationResult | None = None,
        camera_settings: dict[str, Any] | None = None,
        video_enabled: bool = False,
    ) -> "SessionRecorder":
        subject_id = validate_subject_identifier(subject_id)
        if not isinstance(config, ExperimentConfig):
            raise TypeError("Session configuration must be an ExperimentConfig.")
        self.ensure_subject(subject_id)
        session_id = f"session_{datetime.now().strftime('%Y_%m_%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True)
        camera_settings = camera_settings or {}
        metadata = {
            "schema_version": "1.0",
            "software_version": __version__,
            "created_at": utc_now(),
            "session_id": session_id,
            "subject_id": subject_id,
            "tracker_type": tracker_type,
            "camera_settings": camera_settings,
            "preferred_eye_width_min_px": camera_settings.get("preferred_eye_width_min_px"),
            "preferred_eye_width_max_px": camera_settings.get("preferred_eye_width_max_px"),
            "quality_threshold": camera_settings.get("quality_threshold", config.quality_threshold),
            "tracker_backend": camera_settings.get("tracker_backend", tracker_type),
            "camera_resolution": camera_settings.get("camera_resolution"),
            "camera_video_recording": video_enabled,
            "experiment": config.to_dict(),
            "sampling": {"clock": "UTC Unix nanoseconds", "tracker_clock": "monotonic nanoseconds"},
            "environment": {"python": sys.version, "platform": platform.platform()},
            "disclaimer": "Research measurement tool; not a medical diagnostic or treatment device.",
        }
        (session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        calibration_json = json.dumps(asdict(calibration), indent=2) if calibration else None
        if calibration_json:
            (session_dir / "calibration.json").write_text(calibration_json, encoding="utf-8")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO sessions(session_id, subject_id, created_at, experiment_kind,
                   tracker_type, state, session_dir, config_json, calibration_json, software_version)
                   VALUES (?, ?, ?, ?, ?, 'recording', ?, ?, ?, ?)""",
                (session_id, subject_id, metadata["created_at"], config.kind.value, tracker_type,
                 str(session_dir), json.dumps(config.to_dict()), calibration_json, __version__),
            )
        return SessionRecorder(self, session_id, session_dir, video_enabled=video_enabled)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM sessions ORDER BY created_at DESC")]

    def list_subjects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(
                """SELECT s.subject_id, s.created_at, s.notes, s.archived, COUNT(se.session_id) AS session_count,
                   MAX(se.created_at) AS most_recent_session
                   FROM subjects s LEFT JOIN sessions se ON se.subject_id=s.subject_id
                   WHERE (? OR s.archived=0)
                   GROUP BY s.subject_id ORDER BY s.created_at DESC""", (include_archived,)
            )]

    def archive_subject(self, subject_id: str, archived: bool = True) -> None:
        with self._connect() as conn:
            conn.execute('UPDATE subjects SET archived=? WHERE subject_id=?', (int(archived), subject_id))

    def delete_empty_subject(self, subject_id: str) -> None:
        with self._connect() as conn:
            if conn.execute('SELECT COUNT(*) FROM sessions WHERE subject_id=?', (subject_id,)).fetchone()[0]:
                raise ValueError('This subject has sessions. Archive it to preserve its research data.')
            conn.execute('DELETE FROM subjects WHERE subject_id=?', (subject_id,))

    def rename_subject(self, old: str, new: str) -> None:
        new = validate_subject_identifier(new)
        if old == new: return
        backups = []
        try:
            with self._connect() as conn:
                row = conn.execute('SELECT * FROM subjects WHERE subject_id=?', (old,)).fetchone()
                if row is None: raise ValueError('Subject no longer exists.')
                if conn.execute('SELECT 1 FROM subjects WHERE subject_id=?', (new,)).fetchone():
                    raise ValueError('That subject identifier already exists.')
                sessions = list(conn.execute('SELECT session_dir,state FROM sessions WHERE subject_id=?', (old,)))
                if any(s['state'] == 'recording' for s in sessions): raise ValueError('Stop recording before renaming this subject.')
                conn.execute('INSERT INTO subjects(subject_id,created_at,notes,archived) VALUES(?,?,?,?)',
                             (new, row['created_at'], row['notes'], row['archived']))
                conn.execute('UPDATE sessions SET subject_id=? WHERE subject_id=?', (new, old))
                conn.execute('DELETE FROM subjects WHERE subject_id=?', (old,))
                for session in sessions:
                    path = Path(session['session_dir']) / 'metadata.json'
                    original = path.read_text(encoding='utf-8'); backups.append((path, original))
                    data = json.loads(original); data['subject_id'] = new
                    path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        except Exception:
            for path, original in backups: path.write_text(original, encoding='utf-8')
            raise

    def session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            return dict(row) if row else None

    def raw_path(self, session_id: str) -> Path:
        item = self.session(session_id)
        if not item:
            raise KeyError(session_id)
        folder = Path(item["session_dir"])
        parquet = folder / "raw_eye_tracking.parquet"
        return parquet if parquet.exists() else folder / "raw_eye_tracking.csv"

    def load_samples(self, session_id: str):
        if pd is None:
            raise RuntimeError("Pandas is required to inspect stored samples")
        path = self.raw_path(session_id)
        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path)

    def save_metrics(self, session_id: str, metrics: Iterable[dict[str, Any]]) -> None:
        rows = list(metrics)
        with self._connect() as conn:
            for metric in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO metrics(session_id, phase, metric_name, value, unit,
                       metric_kind, quality_ok, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, metric.get("phase", "all"), metric["name"], metric.get("value"),
                     metric.get("unit", ""), metric.get("kind", "estimated metric"),
                     int(metric.get("quality_ok", False)), json.dumps(metric.get("details", {}))),
                )
        session = self.session(session_id)
        if session:
            folder = Path(session["session_dir"])
            with (folder / "derived_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["phase", "name", "value", "unit", "kind", "quality_ok"])
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: row.get(key) for key in writer.fieldnames})

    def load_metrics(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM metrics WHERE session_id=? ORDER BY phase, metric_name", (session_id,)
            )]

    def research_export(self, session_id: str, destination: str | Path) -> Path:
        session = self.session(session_id)
        if not session:
            raise KeyError(session_id)
        target = Path(destination) / session_id
        if target.exists():
            target = Path(destination) / f"{session_id}_export"
        shutil.copytree(session["session_dir"], target)
        return target


class SessionRecorder:
    """Append raw samples immediately; convert without changing row identity at close."""

    def __init__(self, store: DataStore, session_id: str, session_dir: Path, video_enabled: bool = False) -> None:
        self.store = store
        self.session_id = session_id
        self.session_dir = session_dir
        self.csv_path = session_dir / "raw_eye_tracking.csv"
        self.events_path = session_dir / "events.csv"
        self._file = self.csv_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=RAW_COLUMNS, extrasaction="ignore")
        self._writer.writeheader()
        self._events = self.events_path.open("w", newline="", encoding="utf-8")
        self._event_writer = csv.DictWriter(self._events, fieldnames=["timestamp_ns", "event", "phase", "payload_json"])
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

    def event(self, timestamp_ns: int, event: str, phase: str, payload: dict[str, Any] | None = None) -> None:
        self._event_writer.writerow({
            "timestamp_ns": timestamp_ns, "event": event, "phase": phase,
            "payload_json": json.dumps(payload or {}, separators=(",", ":")),
        })
        self._events.flush()

    def append_video_frame(self, frame, fps: float = 30.0) -> None:
        """Record frames only after the researcher explicitly opts in."""
        if not self.video_enabled or cv2 is None or frame is None:
            return
        if self._video_writer is None:
            height, width = frame.shape[:2]
            codec = cv2.VideoWriter_fourcc(*"mp4v")
            self._video_writer = cv2.VideoWriter(
                str(self.session_dir / "camera_video.mp4"), codec, max(1.0, float(fps)), (width, height)
            )
            if not self._video_writer.isOpened():
                self._video_writer.release()
                self._video_writer = None
                raise RuntimeError("Camera video file could not be opened for recording")
        self._video_writer.write(frame)

    def close(self, state: str = 'complete') -> Path:
        if state not in {'complete', 'aborted'}: raise ValueError('Invalid final session state')
        if self.closed:
            return self.session_dir
        self._file.flush(); self._file.close()
        self._events.flush(); self._events.close()
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
        parquet_written = False
        if pd is not None:
            try:
                frame = pd.read_csv(self.csv_path)
                frame.to_parquet(self.session_dir / "raw_eye_tracking.parquet", index=False)
                parquet_written = True
            except (ImportError, ValueError):
                parquet_written = False
        with self.store._connect() as conn:
            conn.execute(
                """UPDATE sessions SET ended_at=?, state=?, sample_count=?,
                   valid_sample_count=? WHERE session_id=?""",
                (utc_now(), state, self.sample_count, self.valid_count, self.session_id),
            )
        metadata_path = self.session_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["ended_at"] = utc_now()
        metadata['state'] = state
        metadata["sample_count"] = self.sample_count
        metadata["valid_sample_count"] = self.valid_count
        metadata["formats"] = {"raw_csv": True, "raw_parquet": parquet_written}
        metadata["formats"]["camera_video"] = bool(self.video_enabled and (self.session_dir / "camera_video.mp4").exists())
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self.closed = True
        return self.session_dir
