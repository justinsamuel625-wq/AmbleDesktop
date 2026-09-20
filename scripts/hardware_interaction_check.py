"""Exercise Hardware-page controls and resizing against a real camera."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from amble.tracking import SimulatedEyeTracker, WebcamEyeTracker
from amble.ui.main_window import MainWindow


def main() -> int:
    app = QApplication([])
    window = MainWindow(); window.show(); window.navigate("Hardware")
    page = window.pages["Hardware"]
    page.backend.setCurrentIndex(page.backend.findData("webcam"))
    page.scan_button.click()
    print("SCAN_ITEMS", page.camera.count(), page.camera.currentText())
    page.connect_button.click()

    def inspect_and_continue() -> None:
        status = window.tracker.status()
        print("START_PREVIEW", isinstance(window.tracker, WebcamEyeTracker), status.camera_open, status.frame_read_success)
        if not isinstance(window.tracker, WebcamEyeTracker):
            print("CAMERA_UNAVAILABLE", "Select a readable camera and close other camera applications before retrying.")
            window.close(); app.quit(); return
        print("TRACKING", status.face_detected, status.left_eye_detected, status.right_eye_detected)
        for width, height in [(900, 650), (1200, 800), (1600, 950)]:
            window.resize(width, height); app.processEvents()
            unclipped = all(button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 18 for button in [page.connect_button, page.stop_button, page.simulator_button, page.calibration_button])
            print("RESIZE", width, height, "BUTTON_TEXT_VISIBLE", unclipped)
        page.overlay.setChecked(False); print("OVERLAY_OFF", not window.tracker._debug_overlay)
        page.overlay.setChecked(True); print("OVERLAY_ON", window.tracker._debug_overlay)
        page.distance_slider.setValue(100)
        print("EYE_RANGE_CLOSER", page.preferred_eye_width_range(), window.tracker.thresholds.preferred_eye_width_min_px, window.tracker.thresholds.preferred_eye_width_max_px)
        page.distance_slider.setValue(45)
        frame_before = window.tracker._frame_number
        page.set_preview_mode("collapsed")
        print("PREVIEW_COLLAPSED", not page.preview_panel.isVisible(), "STREAMING", window.tracker.status().streaming)
        QTimer.singleShot(700, lambda: verify_collapsed(frame_before))

    def verify_collapsed(frame_before: int) -> None:
        print("TRACKING_CONTINUED_COLLAPSED", window.tracker._frame_number > frame_before)
        page.set_preview_mode("medium")
        print("PREVIEW_EXPANDED", page.preview_panel.isVisible())
        page.stop_button.click(); print("STOP_PREVIEW", not window.tracker.status().camera_open)
        page.connect_button.click()
        QTimer.singleShot(1200, verify_restart)

    def verify_restart() -> None:
        print("RESTART_PREVIEW", window.tracker.status().camera_open, window.tracker.status().frame_read_success)
        page.calibration_button.click()
        print("CALIBRATION_NAV", window.stack.currentWidget() is window.pages["Calibration"])
        print("CAMERA_RELEASED_FOR_CALIBRATION", not window.tracker.status().camera_open)
        window.navigate("Hardware"); page.simulator_button.click()
        print("EXPLICIT_SIMULATOR", isinstance(window.tracker, SimulatedEyeTracker), window.tracker.status().streaming)
        window.resize(1000, 760); app.processEvents()
        screenshot_path = window.store.root / "hardware_layout.png"
        window.grab().save(str(screenshot_path)); print("LAYOUT_SCREENSHOT", screenshot_path)
        window.close(); app.quit()

    QTimer.singleShot(2500, inspect_and_continue)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
