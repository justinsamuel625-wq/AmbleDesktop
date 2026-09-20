"""Manual physical-camera integration check; not part of the hardware-free test suite."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from amble.ui.main_window import MainWindow


def main(camera_index: int = 0) -> int:
    app = QApplication([])
    window = MainWindow()
    window.navigate("Hardware")
    window.connect_tracker("webcam", camera_index)

    def verify() -> None:
        page = window.pages["Hardware"]
        status = window.tracker.status()
        preview = page.preview.pixmap()
        print("UI_CAMERA_OPEN", status.camera_open)
        print("UI_BACKEND", page.diagnostics["camera_backend"].text())
        print("UI_FRAME_READ", page.diagnostics["frame_read"].text())
        print("UI_RESOLUTION", page.diagnostics["resolution"].text())
        print("UI_PREVIEW_PIXMAP", bool(preview and not preview.isNull()))
        print("UI_FACE", page.diagnostics["face"].text())
        print("UI_EYES", page.diagnostics["eyes"].text())
        print("LEFT_QUALITY", page.diagnostics["left_quality"].text())
        print("RIGHT_QUALITY", page.diagnostics["right_quality"].text())
        print("OVERALL_QUALITY", page.diagnostics["overall_quality"].text())
        print("OPENNESS", page.diagnostics["openness"].text())
        print("EYE_RESOLUTION", page.diagnostics["eye_resolution"].text())
        print("SHARPNESS", page.diagnostics["sharpness"].text())
        print("LIGHTING", page.diagnostics["lighting"].text())
        print("HEAD_POSE", page.diagnostics["head_pose"].text())
        print("DISTANCE", page.diagnostics["distance"].text())
        print("VALIDITY", page.diagnostics["sample_validity"].text())
        print("GUIDANCE", page.guidance.text())
        print("EXPLANATION", page.explanation.text().replace("\n", " | "))
        window.navigate("Dashboard")
        print("RELEASED_ON_LEAVE", not window.tracker.status().camera_open)
        app.quit()

    QTimer.singleShot(2500, verify)
    result = app.exec()
    window.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 0))
