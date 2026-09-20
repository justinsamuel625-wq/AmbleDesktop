"""Nine-point calibration workflow page."""

import math
import uuid
from datetime import datetime

import numpy as np
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from amble.core.domain import CalibrationPoint, CalibrationResult
from amble.ui.components import StimulusCanvas
from amble.ui.pages.common import heading


class CalibrationPage(QWidget):
    started = Signal(); completed = Signal(object)
    POINTS = [(0.5, .5), (.1, .1), (.5, .1), (.9, .1), (.1, .5), (.9, .5), (.1, .9), (.5, .9), (.9, .9)]

    def __init__(self) -> None:
        super().__init__(); layout, root = heading("Calibration", "Follow each target without moving your head. Calibration reports measurement error; it does not imply clinical accuracy.")
        QVBoxLayout(self).addWidget(root); self.canvas = StimulusCanvas(); layout.addWidget(self.canvas, 1)
        row = QHBoxLayout(); self.progress = QProgressBar(); self.progress.setRange(0, 9); self.result = QLabel("Not calibrated")
        start = QPushButton("Begin 9-point calibration"); start.setObjectName("Primary"); start.clicked.connect(self.begin)
        row.addWidget(start); row.addWidget(self.progress, 1); row.addWidget(self.result); layout.addLayout(row)
        self._index = -1; self.samples = []; self.point_samples = []
        self.timer = QTimer(self); self.timer.setInterval(1300); self.timer.timeout.connect(self.next_point)

    def begin(self) -> None:
        self._index = -1; self.samples = []; self.point_samples = []; self.progress.setValue(0); self.started.emit(); self.next_point(); self.timer.start()

    def accept_sample(self, sample) -> None:
        if self.timer.isActive() and sample.valid: self.point_samples.append(sample)

    def next_point(self) -> None:
        if self._index >= 0:
            self.samples.append((self.POINTS[self._index], list(self.point_samples))); self.point_samples.clear()
        self._index += 1
        if self._index >= len(self.POINTS):
            self.timer.stop(); self.finish(); return
        self.canvas.set_target(*self.POINTS[self._index]); self.progress.setValue(self._index)

    def finish(self) -> None:
        width, height = max(self.canvas.width(), 1), max(self.canvas.height(), 1); points = []
        for (tx, ty), samples in self.samples:
            valid = len(samples) >= 5
            def err(eye: str) -> float:
                xs = [getattr(s, f"{eye}_gaze_x") for s in samples if getattr(s, f"{eye}_gaze_x") is not None]
                ys = [getattr(s, f"{eye}_gaze_y") for s in samples if getattr(s, f"{eye}_gaze_y") is not None]
                return math.hypot((float(np.mean(xs)) - tx) * width, (float(np.mean(ys)) - ty) * height) if xs and ys else float("nan")
            points.append(CalibrationPoint(tx, ty, err("left"), err("right"), err("binocular"), valid, len(samples)))
        result = CalibrationResult(uuid.uuid4().hex, datetime.now().astimezone().isoformat(), width, height, points)
        avg = result.average_error_px; self.progress.setValue(9)
        self.result.setText(f"{result.quality.upper()} · mean binocular error {avg:.1f}px" if avg is not None else "FAILED · insufficient samples")
        self.completed.emit(result)



__all__ = ["CalibrationPage"]
