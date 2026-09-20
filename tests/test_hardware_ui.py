import pytest
from PySide6.QtCore import QSettings

from amble.tracking.base import TrackerStatus
from amble.ui import main_window
from amble.ui.pages import hardware
from amble.ui.main_window import HardwarePage, MainWindow


@pytest.fixture(autouse=True)
def isolated_hardware_settings(monkeypatch, tmp_path):
    settings = QSettings(str(tmp_path / "hardware-settings.ini"), QSettings.IniFormat)
    settings.clear()
    monkeypatch.setattr(hardware, "QSettings", lambda: settings)
    yield settings
    settings.clear()


def test_hardware_diagnostics_render_camera_state(qtbot):
    page = HardwarePage(); qtbot.addWidget(page)
    page.update_status(TrackerStatus(
        connected=True, streaming=True, resolution=(1280, 720), fps=29.8,
        both_eyes_detected=True, confidence=.82, message="Tracking both eyes",
        backend="MSMF", camera_index=1, camera_open=True, frame_read_success=True,
        face_detected=True, left_eye_detected=True, right_eye_detected=True,
        left_eye_quality=.91, right_eye_quality=.76, overall_quality=.76,
        left_eye_openness="OPEN", right_eye_openness="SQUINTING",
        left_eye_pixel_width=62, right_eye_pixel_width=59,
        left_eye_sharpness=110, right_eye_sharpness=72, lighting_quality="GOOD",
        head_pose_state="GOOD", distance_quality="IDEAL", binocular_valid=False,
        guidance="Open right eye fully", quality_explanation="Right eye openness partial",
    ))
    assert page.diagnostics["camera_backend"].text() == "MSMF"
    assert page.diagnostics["camera_open"].text() == "YES"
    assert page.diagnostics["frame_read"].text() == "SUCCESS"
    assert page.diagnostics["eyes"].text() == "YES / YES"
    assert page.diagnostics["left_quality"].text() == "91%"
    assert page.diagnostics["right_quality"].text() == "76%"
    assert page.diagnostics["overall_quality"].text() == "76%"
    assert page.diagnostics["openness"].text() == "OPEN / SQUINTING"
    assert page.guidance.text() == "Open right eye fully"
    assert page.metric_left.text().startswith("Quality 91%")
    assert "Overall 76%" in page.metric_binocular.text()
    assert page.distance_guidance.text() == "Distance good"
    assert "preferred: 40–75 px" in page.distance_live.text()


def test_hardware_buttons_are_sized_connected_and_keyboard_focusable(qtbot):
    page = HardwarePage(); qtbot.addWidget(page)
    for button in [page.scan_button, page.connect_button, page.stop_button, page.simulator_button, page.calibration_button]:
        assert button.minimumHeight() >= 38
        assert button.focusPolicy().name == "StrongFocus"
        assert button.sizeHint().width() >= button.fontMetrics().horizontalAdvance(button.text())
    with qtbot.waitSignal(page.scan_requested, timeout=500): page.scan_button.click()
    with qtbot.waitSignal(page.disconnect_requested, timeout=500):
        page.stop_button.setEnabled(True); page.stop_button.click()
    with qtbot.waitSignal(page.calibration_requested, timeout=500):
        page.calibration_button.setEnabled(True); page.calibration_button.click()
    with qtbot.waitSignal(page.connect_requested, timeout=500) as signal:
        page.connect_button.click()
    assert signal.args[0] == "simulated"
    new_threshold = 75 if page.quality_threshold.value() != 75 else 74
    with qtbot.waitSignal(page.threshold_changed, timeout=500) as signal:
        page.quality_threshold.setValue(new_threshold)
    assert signal.args == [new_threshold / 100]
    page.overlay.click(); assert not page.overlay.isChecked()
    page.head_comp.click(); assert not page.head_comp.isChecked()
    assert page.backend.count() == 3


def test_eye_resolution_preference_emits_and_persists(qtbot, isolated_hardware_settings):
    page = HardwarePage(); qtbot.addWidget(page)
    with qtbot.waitSignal(page.eye_range_changed, timeout=500) as signal:
        page.distance_slider.setValue(100)
    assert signal.args == [55, 99]
    assert page.preferred_eye_width_range() == (55, 99)
    restored = HardwarePage(); qtbot.addWidget(restored)
    assert restored.preferred_eye_width_range() == (55, 99)


def test_preview_modes_collapse_visual_only_and_persist(qtbot, tmp_path):
    window = MainWindow(tmp_path / "data"); qtbot.addWidget(window); window.show(); window.navigate("Hardware")
    page = window.pages["Hardware"]
    assert window.tracker.status().streaming
    page.set_preview_mode("collapsed"); qtbot.wait(20)
    assert not page.preview_panel.isVisible()
    assert page.preview_toggle.text() == "Expand Preview"
    assert window.tracker.status().streaming
    page.preview_toggle.click(); qtbot.wait(20)
    assert page.preview_panel.isVisible()
    assert page.preview_mode.currentData() == "medium"
    assert window.tracker.status().streaming
    window.close()


def test_webcam_failure_does_not_restart_simulator(qtbot, monkeypatch, tmp_path):
    window = MainWindow(tmp_path); qtbot.addWidget(window)
    initial = window.tracker

    class FailingWebcam:
        def __init__(self):
            raise RuntimeError("deliberate camera failure")

    messages = []
    monkeypatch.setattr(main_window, "WebcamEyeTracker", FailingWebcam)
    monkeypatch.setattr(main_window.QMessageBox, "critical", lambda *args: messages.append(args[-1]))
    window.connect_tracker("webcam", 0)

    assert window.tracker is initial
    assert not window.tracker.status().streaming
    assert "No simulator was substituted" in messages[0]
    window.close()
