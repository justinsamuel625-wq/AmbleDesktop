"""Dashboard and session-list page."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from amble.storage import DataStore
from amble.ui.pages.common import DISCLAIMER, heading


class DashboardPage(QWidget):
    session_requested = Signal(str)
    def __init__(self, store: DataStore) -> None:
        super().__init__(); self.store = store
        layout, root = heading("Research Dashboard", "Session status, acquisition quality, and reproducible analysis at a glance.")
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(root)
        cards = QHBoxLayout(); self.subjects = QLabel("0\nSUBJECTS"); self.sessions = QLabel("0\nSESSIONS"); self.samples = QLabel("0\nRAW SAMPLES")
        for item in [self.subjects, self.sessions, self.samples]:
            item.setAlignment(Qt.AlignCenter); item.setMinimumHeight(90); item.setStyleSheet("background:#172532;border:1px solid #2b3c4c;border-radius:6px;font-size:16px;")
            cards.addWidget(item)
        layout.addLayout(cards)
        notice = QLabel(DISCLAIMER + " Webcam proxy measurements are not clinically equivalent to an ophthalmic eye tracker.")
        notice.setObjectName("Safety"); notice.setWordWrap(True); layout.addWidget(notice)
        self.recent = QTableWidget(0, 6); self.recent.setHorizontalHeaderLabels(["Session", "Subject", "Experiment", "Tracker", "Samples", "Created"])
        self.recent.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.recent, 1)
        self.recent.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recent.setToolTip('Double-click a session to open its analytics.')
        self.recent.cellDoubleClicked.connect(lambda row, column: self.session_requested.emit(self.recent.item(row,0).text()))
        self.refresh()

    def refresh(self) -> None:
        subjects, sessions = self.store.list_subjects(), self.store.list_sessions()
        self.subjects.setText(f"{len(subjects)}\nSUBJECTS"); self.sessions.setText(f"{len(sessions)}\nSESSIONS")
        self.samples.setText(f"{sum(s['sample_count'] for s in sessions):,}\nRAW SAMPLES")
        self.recent.setRowCount(min(12, len(sessions)))
        for r, session in enumerate(sessions[:12]):
            values = [session["session_id"], session["subject_id"], session["experiment_kind"], session["tracker_type"], session["sample_count"], session["created_at"][:19]]
            for c, value in enumerate(values): self.recent.setItem(r, c, QTableWidgetItem(str(value)))



__all__ = ["DashboardPage"]
