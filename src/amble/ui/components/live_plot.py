"""Bounded real-time trace widget used during recording."""

from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class LivePlot(QWidget):
    """Small bounded scrolling plot rendered at the UI refresh rate."""

    def __init__(self) -> None:
        super().__init__()
        self.points = deque(maxlen=7200)
        self.window_s = 10
        self.setMinimumHeight(125)

    def append(self, seconds, target, left, right) -> None:
        self.points.append((seconds, target, left, right))
        while self.points and self.points[0][0] < seconds - self.window_s:
            self.points.popleft()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111c26"))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#bdcbd6"))
        painter.drawText(10, 18, f"Last {self.window_s} s — target X / left X / right X")
        if not self.points:
            return
        end = self.points[-1][0]
        start = max(0, end - self.window_s)
        width = max(self.width() - 20, 1)
        height = max(self.height() - 40, 1)
        for column, color in [(1, "#e0b45b"), (2, "#56a9d6"), (3, "#df6c78")]:
            painter.setPen(QPen(QColor(color), 1.5))
            previous = None
            for row in self.points:
                value = row[column]
                if value is None or not math.isfinite(value):
                    previous = None
                    continue
                point = QPointF(
                    10 + (row[0] - start) / self.window_s * width,
                    30 + (1 - max(0, min(1, value))) * height,
                )
                if previous is not None:
                    painter.drawLine(previous, point)
                previous = point


__all__ = ["LivePlot"]
