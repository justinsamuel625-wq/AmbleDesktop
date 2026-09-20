"""Experiment target and optional gaze visualization canvas."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class StimulusCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(560, 380)
        self.target = (0.5, 0.5)
        self.target_size_px = 5
        self.gaze: deque[tuple[float, float]] = deque(maxlen=300)
        self.show_gaze = False
        self.setStyleSheet("background:#f5f6f2; border:1px solid #40515f;")

    def set_target(self, x: float, y: float) -> None:
        self.target = (x, y)
        self.update()

    def set_target_size(self, radius_px: int) -> None:
        self.target_size_px = max(3, min(30, int(radius_px)))
        self.update()

    def add_gaze(self, x: float | None, y: float | None) -> None:
        if x is not None and y is not None:
            self.gaze.append((x, y))
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.show_gaze:
            painter.setPen(QPen(QColor(56, 133, 174, 90), 2))
            for x, y in self.gaze:
                painter.drawPoint(QPointF(x * self.width(), y * self.height()))
        x = self.target[0] * self.width()
        y = self.target[1] * self.height()
        painter.setPen(QPen(QColor("#1c252d"), 3))
        painter.drawLine(QPointF(x - 13, y), QPointF(x + 13, y))
        painter.drawLine(QPointF(x, y - 13), QPointF(x, y + 13))
        painter.setPen(QPen(QColor("#bb3846"), 3))
        painter.drawEllipse(QPointF(x, y), self.target_size_px, self.target_size_px)


__all__ = ["StimulusCanvas"]
