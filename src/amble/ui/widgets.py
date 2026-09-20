from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget
import math


class LivePlot(QWidget):
    """Small bounded scrolling plot rendered at the UI refresh rate."""
    def __init__(self):
        super().__init__(); self.points=deque(maxlen=7200); self.window_s=10; self.setMinimumHeight(125)
    def append(self, seconds, target, left, right):
        self.points.append((seconds,target,left,right))
        while self.points and self.points[0][0]<seconds-self.window_s:self.points.popleft()
        self.update()
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#111c26'));painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor('#bdcbd6'));painter.drawText(10,18,f'Last {self.window_s} s — target X / left X / right X')
        if not self.points:return
        end=self.points[-1][0]; start=max(0,end-self.window_s); width=max(self.width()-20,1); height=max(self.height()-40,1)
        for col,color in [(1,'#e0b45b'),(2,'#56a9d6'),(3,'#df6c78')]:
            painter.setPen(QPen(QColor(color),1.5));previous=None
            for row in self.points:
                value=row[col]
                if value is None or not math.isfinite(value):previous=None;continue
                point=QPointF(10+(row[0]-start)/self.window_s*width,30+(1-max(0,min(1,value)))*height)
                if previous is not None:painter.drawLine(previous,point)
                previous=point


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
        x, y = self.target[0] * self.width(), self.target[1] * self.height()
        painter.setPen(QPen(QColor("#1c252d"), 3))
        painter.drawLine(QPointF(x - 13, y), QPointF(x + 13, y))
        painter.drawLine(QPointF(x, y - 13), QPointF(x, y + 13))
        painter.setPen(QPen(QColor("#bb3846"), 3))
        painter.drawEllipse(QPointF(x, y), self.target_size_px, self.target_size_px)


class CameraView(QLabel):
    def __init__(self) -> None:
        super().__init__("Camera preview inactive")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 270)
        self.setStyleSheet("background:#080d12; border:1px solid #34495c; color:#748796;")
