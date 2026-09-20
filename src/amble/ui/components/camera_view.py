"""Camera preview surface."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class CameraView(QLabel):
    def __init__(self) -> None:
        super().__init__("Camera preview inactive")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 270)
        self.setStyleSheet(
            "background:#080d12; border:1px solid #34495c; color:#748796;"
        )


__all__ = ["CameraView"]
