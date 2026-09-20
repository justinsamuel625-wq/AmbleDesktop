from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from amble.analysis import METRIC_DEFINITIONS, analyze_session
from amble.domain import (
    CalibrationPoint, CalibrationResult, ExperimentConfig, ExperimentKind, PursuitTrajectory,
    validate_subject_identifier,
)
from amble.experiments import DEFAULT_EXPERIMENTS, ExperimentRuntime
from amble.storage import DataStore
from amble.tracking import OpenFaceEyeTracker, SimulatedEyeTracker, WebcamEyeTracker, enumerate_cameras, validate_opencv
from amble.ui.theme import APP_STYLE
from amble.ui.widgets import CameraView, StimulusCanvas, LivePlot
from amble.session_control import ProtocolClock
from amble.ui.explorer import RawDataPage
from amble.ui.analytics import AnalyticsPage
from amble.ui.subjects import SubjectsPage
from amble.ui.settings import SettingsPage
from amble.preferences import preference
from amble.research import latest_attempts

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import plotly.graph_objects as go
    from plotly.offline import plot
    from plotly.subplots import make_subplots
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    go = None
    QWebEngineView = None


DISCLAIMER = "This is a research measurement tool and is not a medical diagnostic or treatment device."
LOGGER = logging.getLogger(__name__)


def heading(title: str, subtitle: str = "") -> tuple[QVBoxLayout, QWidget]:
    root = QWidget(); layout = QVBoxLayout(root); layout.setContentsMargins(24, 20, 24, 20)
    label = QLabel(title); label.setObjectName("PageTitle"); layout.addWidget(label)
    if subtitle:
        sub = QLabel(subtitle); sub.setObjectName("Muted"); sub.setWordWrap(True); layout.addWidget(sub)
    return layout, root


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




class HardwarePage(QWidget):
    connect_requested = Signal(str, object)
    disconnect_requested = Signal()
    calibration_requested = Signal()
    scan_requested = Signal()
    threshold_changed = Signal(float)
    eye_range_changed = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        settings = QSettings()
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        content = QWidget(); self.scroll.setWidget(content); outer.addWidget(self.scroll)
        layout = QVBoxLayout(content); layout.setContentsMargins(24, 16, 24, 16); layout.setSpacing(9)
        title = QLabel("Hardware"); title.setObjectName("PageTitle"); layout.addWidget(title)
        subtitle = QLabel("Camera access occurs only after an explicit action. Quality describes sample measurability, not clinical accuracy.")
        subtitle.setObjectName("Muted"); subtitle.setWordWrap(True); layout.addWidget(subtitle)
        setup = QGroupBox("Acquisition setup"); form = QFormLayout(setup); form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.backend = QComboBox(); self.backend.addItem("Simulator (recommended for first run)", "simulated"); self.backend.addItem("Webcam — OpenCV research proxy", "webcam")
        self.backend.addItem("OpenFace — external FeatureExtraction", "openface")
        self.camera = QComboBox(); self.camera.addItem("Camera 0", 0)
        self.scan_button = QPushButton("Scan Cameras"); self.scan_button.setToolTip("Probe MSMF, DirectShow, and automatic backends; only readable cameras are listed.")
        self.scan_button.clicked.connect(self.scan_requested)
        cam_row = QHBoxLayout(); cam_row.addWidget(self.camera, 1); cam_row.addWidget(self.scan_button)
        self.head_comp = QCheckBox("Head-pose compensation (not implemented)"); self.head_comp.setChecked(False)
        self.head_comp.setEnabled(False); self.head_comp.setToolTip('The webcam reports head pose but does not fit a compensated gaze transform.')
        self.overlay = QCheckBox("Show facial/eye landmark debug overlay"); self.overlay.setChecked(preference('research/overlay'))
        self.quality_threshold = QSpinBox(); self.quality_threshold.setRange(20, 95)
        self.quality_threshold.setValue(preference('hardware/minimum_binocular_quality', settings))
        self.quality_threshold.setSuffix(" %")
        self.quality_threshold.setToolTip("Both eyes and overall quality must meet this threshold for a valid binocular sample.")
        self.quality_threshold.valueChanged.connect(self._quality_threshold_changed)

        self.distance_preset = QComboBox()
        self.distance_preset.addItem("Farther / comfortable", 0); self.distance_preset.addItem("Balanced / default", 45)
        self.distance_preset.addItem("Closer / higher resolution", 100); self.distance_preset.addItem("Custom", None)
        self.distance_preset.setCurrentIndex(1)
        self.distance_slider = QSlider(Qt.Horizontal); self.distance_slider.setRange(0, 100); self.distance_slider.setTickInterval(10)
        self.distance_slider.setValue(int(settings.value("hardware/eye_distance_preference", 45)))
        slider_row = QWidget(); slider_layout = QHBoxLayout(slider_row); slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.addWidget(QLabel("Farther")); slider_layout.addWidget(self.distance_slider, 1); slider_layout.addWidget(QLabel("Closer"))
        self.eye_width_min = QSpinBox(); self.eye_width_min.setRange(20, 100); self.eye_width_min.setSuffix(" px")
        self.eye_width_max = QSpinBox(); self.eye_width_max.setRange(30, 140); self.eye_width_max.setSuffix(" px")
        self.eye_width_min.setValue(preference('hardware/preferred_eye_width_min_px', settings))
        self.eye_width_max.setValue(max(self.eye_width_min.value()+5, preference('hardware/preferred_eye_width_max_px', settings)))
        range_row = QWidget(); range_layout = QHBoxLayout(range_row); range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.addWidget(QLabel("Minimum")); range_layout.addWidget(self.eye_width_min); range_layout.addSpacing(12)
        range_layout.addWidget(QLabel("Maximum")); range_layout.addWidget(self.eye_width_max); range_layout.addStretch()
        self.preferred_range_label = QLabel(); self.preferred_range_label.setObjectName("Muted")
        form.addRow("Tracking backend", self.backend); form.addRow("Camera device", cam_row)
        form.addRow("Minimum binocular quality", self.quality_threshold)
        form.addRow("Distance preset", self.distance_preset); form.addRow("Camera distance preference", slider_row)
        form.addRow("Preferred eye resolution", range_row); form.addRow("", self.preferred_range_label)
        form.addRow("", self.head_comp); form.addRow("", self.overlay)
        self.connect_button = QPushButton("Request Camera Access / Start Preview"); self.connect_button.setObjectName("Primary")
        self.stop_button = QPushButton("Stop Preview"); self.stop_button.setToolTip("Stop acquisition and release the selected camera.")
        self.simulator_button = QPushButton("Use Simulator Instead"); self.simulator_button.setToolTip("Explicitly switch to synthetic data; Amble never does this automatically.")
        self.calibration_button = QPushButton("Start Calibration"); self.calibration_button.setToolTip("Open the calibration workflow using the selected tracker.")
        for button in [self.scan_button, self.connect_button, self.stop_button, self.simulator_button, self.calibration_button]:
            button.setMinimumHeight(38); button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); button.setFocusPolicy(Qt.StrongFocus)
        self.connect_button.clicked.connect(lambda: self.connect_requested.emit(self.backend.currentData(), self.camera.currentData()))
        self.stop_button.clicked.connect(self.disconnect_requested); self.calibration_button.clicked.connect(self.calibration_requested)
        self.simulator_button.clicked.connect(self.use_simulator)
        controls = QGridLayout(); controls.setHorizontalSpacing(10); controls.setVerticalSpacing(8)
        controls.addWidget(self.connect_button, 0, 0, 1, 2); controls.addWidget(self.stop_button, 1, 0)
        controls.addWidget(self.simulator_button, 1, 1); controls.addWidget(self.calibration_button, 2, 0, 1, 2)
        controls.setColumnStretch(0, 1); controls.setColumnStretch(1, 1)
        self.preview = CameraView(); self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setMinimumSize(120, 80); self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview_panel = QGroupBox("Live camera preview")
        preview_layout = QVBoxLayout(self.preview_panel); preview_layout.setContentsMargins(8, 12, 8, 8); preview_layout.addWidget(self.preview)
        self.preview_mode = QComboBox(); self.preview_mode.addItem("Expanded", "expanded"); self.preview_mode.addItem("Medium", "medium"); self.preview_mode.addItem("Collapsed", "collapsed")
        self.preview_toggle = QPushButton("Collapse Preview"); self.preview_toggle.setMinimumHeight(34); self.preview_toggle.setToolTip("Hide only the image; camera acquisition and tracking continue.")
        preview_controls = QHBoxLayout(); preview_controls.addWidget(QLabel("Preview size")); preview_controls.addWidget(self.preview_mode); preview_controls.addStretch(); preview_controls.addWidget(self.preview_toggle)
        layout.addLayout(preview_controls)
        self.status = QLabel("Disconnected"); self.status.setObjectName("Muted"); self.status.setWordWrap(True)
        self.guidance = QLabel("Center your face"); self.guidance.setObjectName("Safety"); self.guidance.setAlignment(Qt.AlignCenter); self.guidance.setMinimumHeight(42)
        self.distance_guidance = QLabel("Distance unavailable"); self.distance_guidance.setObjectName("Warning"); self.distance_guidance.setAlignment(Qt.AlignCenter)
        self.distance_live = QLabel("Current eye size: — / — px  ·  Preferred range: —")
        self.distance_live.setAlignment(Qt.AlignCenter); self.distance_live.setObjectName("Muted")

        live_metrics = QGroupBox("Live metrics")
        metrics_grid = QGridLayout(live_metrics); metrics_grid.setHorizontalSpacing(8)
        self.metric_left = QLabel("Quality —\nOpen —\nWidth —")
        self.metric_right = QLabel("Quality —\nOpen —\nWidth —")
        self.metric_binocular = QLabel("Valid —\nOverall —")
        self.metric_camera = QLabel("FPS —\nDistance —")
        self.metric_head = QLabel("Pose —\nLighting —")
        for column, (heading_text, metric) in enumerate([
            ("LEFT EYE", self.metric_left), ("RIGHT EYE", self.metric_right), ("BINOCULAR", self.metric_binocular),
            ("CAMERA", self.metric_camera), ("HEAD", self.metric_head),
        ]):
            card = QFrame(); card.setObjectName("MetricCard"); card_layout = QVBoxLayout(card); card_layout.setContentsMargins(9, 7, 9, 7)
            heading_label = QLabel(heading_text); heading_label.setObjectName("MetricHeading"); card_layout.addWidget(heading_label); card_layout.addWidget(metric)
            metrics_grid.addWidget(card, 0, column); metrics_grid.setColumnStretch(column, 1)
        diagnostics = QGroupBox("Hardware diagnostics"); self.diagnostics_box = diagnostics; diagnostics.setVisible(preference('research/diagnostics')); diagnostics_form = QFormLayout(diagnostics)
        diagnostics_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow); diagnostics_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.diagnostics = {}
        for key, title in [
            ("opencv_version", "OpenCV version"), ("opencv_path", "OpenCV module"),
            ("landmark_backend", "Landmark backend"), ("python", "Python interpreter"), ("camera_index", "Selected camera"),
            ("camera_backend", "Camera backend"), ("camera_open", "Camera open"),
            ("resolution", "Resolution"), ("fps", "Measured FPS"),
            ("frame_read", "Frame read"), ("face", "Face detected"),
            ("eyes", "Left / right eye detected"), ("left_quality", "Left eye quality"),
            ("right_quality", "Right eye quality"), ("overall_quality", "Overall tracking quality"),
            ("openness", "Left / right openness"), ("head_pose", "Head pose"),
            ("eye_resolution", "Eye resolution"), ("sharpness", "Eye sharpness"),
            ("lighting", "Lighting quality"), ("distance", "Distance quality"),
            ("sample_validity", "Sample validity"),
        ]:
            value = QLabel("—"); value.setTextInteractionFlags(Qt.TextSelectableByMouse); value.setWordWrap(True)
            self.diagnostics[key] = value; diagnostics_form.addRow(title, value)
        self.why_button = QPushButton("Why this quality score?"); self.why_button.setCheckable(True); self.why_button.setMinimumHeight(34)
        self.explanation = QLabel(""); self.explanation.setWordWrap(True); self.explanation.setObjectName("Muted"); self.explanation.setVisible(False)
        self.why_button.toggled.connect(self.explanation.setVisible)
        diagnostics_form.addRow(self.why_button); diagnostics_form.addRow(self.explanation)

        details_content = QWidget(); details_layout = QVBoxLayout(details_content); details_layout.setContentsMargins(4, 4, 4, 4)
        details_layout.addWidget(setup); details_layout.addLayout(controls); details_layout.addWidget(self.status); details_layout.addWidget(diagnostics)
        lower = QWidget(); lower_layout = QVBoxLayout(lower); lower_layout.setContentsMargins(0, 0, 0, 0); lower_layout.setSpacing(6)
        lower_layout.addWidget(self.guidance); lower_layout.addWidget(self.distance_guidance); lower_layout.addWidget(self.distance_live)
        lower_layout.addWidget(live_metrics); lower_layout.addStretch()
        self.splitter = QSplitter(Qt.Vertical); self.splitter.setChildrenCollapsible(False); self.splitter.setHandleWidth(9)
        self.splitter.addWidget(self.preview_panel); self.splitter.addWidget(lower); self.splitter.setStretchFactor(0, 2); self.splitter.setStretchFactor(1, 3)
        layout.addWidget(self.splitter); layout.addWidget(details_content)
        self.splitter.handle(1).setToolTip('Drag to resize the preview. Camera resolution and acquisition are unchanged.')

        self.camera.currentIndexChanged.connect(self.update_selected_camera)
        self.backend.currentIndexChanged.connect(self.update_controls)
        self.distance_slider.valueChanged.connect(self._distance_slider_changed)
        self.distance_preset.currentIndexChanged.connect(self._preset_changed)
        self.eye_width_min.valueChanged.connect(self._eye_range_changed)
        self.eye_width_max.valueChanged.connect(self._eye_range_changed)
        self.preview_mode.currentIndexChanged.connect(lambda: self.set_preview_mode(self.preview_mode.currentData()))
        self.preview_toggle.clicked.connect(self.toggle_preview)
        self.splitter.splitterMoved.connect(self._splitter_moved)
        saved_backend = str(settings.value("hardware/backend", "simulated")); backend_index = self.backend.findData(saved_backend)
        if backend_index >= 0: self.backend.setCurrentIndex(backend_index)
        saved_camera = preference('hardware/camera_index', settings)
        if self.camera.findData(saved_camera) < 0: self.camera.addItem(f'Camera {saved_camera}', saved_camera)
        camera_index = self.camera.findData(saved_camera)
        if camera_index >= 0: self.camera.setCurrentIndex(camera_index)
        saved_mode = str(settings.value("hardware/preview_mode", "medium")); mode_index = self.preview_mode.findData(saved_mode)
        self.preview_mode.setCurrentIndex(max(0, mode_index))
        self._update_range_label(); self.set_preview_mode(saved_mode)
        expected_ranges={(28,55):0,(40,75):1,(55,99):2}
        self.distance_preset.blockSignals(True);self.distance_preset.setCurrentIndex(expected_ranges.get(self.preferred_eye_width_range(),3));self.distance_preset.blockSignals(False)
        saved_sizes = str(settings.value('hardware/preview_splitter_sizes', '')).split(',')
        if len(saved_sizes) == 2:
            try:
                sizes = [max(80, min(900, int(s))) for s in saved_sizes]
                if saved_mode != 'collapsed': self.splitter.setFixedHeight(sum(sizes)+9); self.splitter.setSizes(sizes)
            except ValueError: pass
        self.populate_environment_diagnostics()
        self.update_controls()

    def use_simulator(self) -> None:
        index = self.backend.findData("simulated"); self.backend.setCurrentIndex(index)
        self.connect_requested.emit("simulated", None)

    def _quality_threshold_changed(self, value: int) -> None:
        QSettings().setValue("hardware/minimum_binocular_quality", value)
        self.threshold_changed.emit(value / 100)

    def _preset_changed(self) -> None:
        value = self.distance_preset.currentData()
        if value is not None and self.distance_slider.value() != value: self.distance_slider.setValue(value)

    def _distance_slider_changed(self, value: int) -> None:
        minimum = 28 + round(value * .267)
        maximum = 55 + round(value * .444)
        self.eye_width_min.blockSignals(True); self.eye_width_max.blockSignals(True)
        self.eye_width_min.setValue(minimum); self.eye_width_max.setValue(maximum)
        self.eye_width_min.blockSignals(False); self.eye_width_max.blockSignals(False)
        QSettings().setValue("hardware/eye_distance_preference", value)
        for index in range(self.distance_preset.count()):
            if self.distance_preset.itemData(index) == value:
                self.distance_preset.blockSignals(True); self.distance_preset.setCurrentIndex(index); self.distance_preset.blockSignals(False); break
        else:
            self.distance_preset.blockSignals(True); self.distance_preset.setCurrentIndex(self.distance_preset.count() - 1); self.distance_preset.blockSignals(False)
        self._persist_eye_range()

    def _eye_range_changed(self) -> None:
        minimum, maximum = self.eye_width_min.value(), self.eye_width_max.value()
        if maximum <= minimum:
            if self.sender() is self.eye_width_min: self.eye_width_max.setValue(min(140, minimum + 5))
            else: self.eye_width_min.setValue(max(20, maximum - 5))
        self.distance_preset.blockSignals(True); self.distance_preset.setCurrentIndex(self.distance_preset.count() - 1); self.distance_preset.blockSignals(False)
        self._persist_eye_range()

    def _persist_eye_range(self) -> None:
        minimum, maximum = self.preferred_eye_width_range()
        settings = QSettings(); settings.setValue("hardware/preferred_eye_width_min_px", minimum); settings.setValue("hardware/preferred_eye_width_max_px", maximum)
        self._update_range_label(); self.eye_range_changed.emit(minimum, maximum)

    def preferred_eye_width_range(self) -> tuple[int, int]:
        return self.eye_width_min.value(), self.eye_width_max.value()

    def _update_range_label(self) -> None:
        minimum, maximum = self.preferred_eye_width_range()
        self.preferred_range_label.setText(f"Preferred range: {minimum}–{maximum} px per eye. This changes only the resolution component of quality.")

    def set_preview_mode(self, mode: str) -> None:
        mode = mode if mode in {"expanded", "medium", "collapsed"} else "medium"
        index = self.preview_mode.findData(mode)
        if index >= 0 and self.preview_mode.currentIndex() != index:
            self.preview_mode.blockSignals(True); self.preview_mode.setCurrentIndex(index); self.preview_mode.blockSignals(False)
        collapsed = mode == "collapsed"
        self.preview_panel.setVisible(not collapsed)
        self.splitter.setFixedHeight(260 if collapsed else 740 if mode == 'expanded' else 530)
        if not collapsed:
            total = max(self.splitter.height(), 500); top = int(total * (.62 if mode == "expanded" else .40)); self.splitter.setSizes([top, max(220, total - top)])
        self.preview_toggle.setText("Expand Preview" if collapsed else "Collapse Preview")
        QSettings().setValue("hardware/preview_mode", mode)

    def toggle_preview(self) -> None:
        self.set_preview_mode("medium" if self.preview_mode.currentData() == "collapsed" else "collapsed")

    def _splitter_moved(self) -> None:
        if self.preview_panel.isVisible(): QSettings().setValue("hardware/preview_splitter_sizes", ",".join(str(size) for size in self.splitter.sizes()))

    def populate_environment_diagnostics(self) -> None:
        try:
            info = validate_opencv()
            self.diagnostics["opencv_version"].setText(info.version)
            self.diagnostics["opencv_path"].setText(info.module_path)
            self.diagnostics["python"].setText(info.python_executable)
            self.diagnostics["landmark_backend"].setText(info.landmark_backend)
        except Exception as exc:
            self.diagnostics["opencv_version"].setText("INVALID")
            self.diagnostics["opencv_path"].setText(str(exc))

    def update_selected_camera(self) -> None:
        value = self.camera.currentData()
        self.diagnostics["camera_index"].setText(str(value) if value is not None else "None detected")
        if value is not None: QSettings().setValue("hardware/camera_index", value)
        self.update_controls()

    def update_controls(self) -> None:
        needs_camera = self.backend.currentData() == "webcam"
        QSettings().setValue("hardware/backend", self.backend.currentData())
        self.connect_button.setEnabled(not needs_camera or self.camera.currentData() is not None)
        self.connect_button.setToolTip("Select or scan for a readable camera first." if not self.connect_button.isEnabled() else "Connect the selected tracker and start acquisition.")

    def scan(self) -> None:
        self.scan_button.setEnabled(False); self.scan_button.setText("Scanning…"); self.camera.clear()
        try:
            cameras = enumerate_cameras()
        except Exception as exc:
            self.camera.addItem("Camera scan failed", None); self.set_error(str(exc)); return
        finally:
            self.scan_button.setEnabled(True); self.scan_button.setText("Scan Cameras")
        for camera in cameras:
            width, height = camera.resolution
            self.camera.addItem(f"{camera.name} · {camera.backend} · {width}×{height}", camera.index)
        if not cameras:
            self.camera.addItem("No accessible cameras found", None)
            self.status.setText("No camera returned a readable frame. Check Windows camera privacy and close other camera applications.")
        else:
            self.status.setText(f"Found {len(cameras)} camera device(s). Select one and request access.")
        self.update_selected_camera()

    def update_status(self, status) -> None:
        self.status.setText(f"{status.message}  |  {status.resolution[0]}×{status.resolution[1]}  |  {status.fps:.1f} FPS  |  both eyes: {'yes' if status.both_eyes_detected else 'no'}  |  confidence: {status.confidence:.0%}")
        self.guidance.setText(status.guidance or "Center your face")
        distance_instruction = {"TOO FAR": "Move closer", "TOO CLOSE": "Move farther back", "IDEAL": "Distance good", "ACCEPTABLE": "Distance good"}.get(status.distance_quality, "Distance unavailable")
        self.distance_guidance.setText(distance_instruction)
        minimum, maximum = self.preferred_eye_width_range()
        self.distance_live.setText(f"Current left eye size: {status.left_eye_pixel_width:.0f} px  ·  right: {status.right_eye_pixel_width:.0f} px  ·  preferred: {minimum}–{maximum} px")
        self.metric_left.setText(f"Quality {status.left_eye_quality:.0%}\nOpen {status.left_eye_openness}\nWidth {status.left_eye_pixel_width:.0f} px")
        self.metric_right.setText(f"Quality {status.right_eye_quality:.0%}\nOpen {status.right_eye_openness}\nWidth {status.right_eye_pixel_width:.0f} px")
        self.metric_binocular.setText(f"Valid {'YES' if status.binocular_valid else 'NO'}\nOverall {status.overall_quality:.0%}")
        self.metric_camera.setText(f"FPS {status.fps:.1f}\nDistance {status.distance_quality}")
        self.metric_head.setText(f"Pose {status.head_pose_state}\nLighting {status.lighting_quality}")
        values = {
            "camera_index": status.camera_index if status.camera_index is not None else self.camera.currentData(),
            "camera_backend": status.backend or "—", "camera_open": "YES" if status.camera_open else "NO",
            "resolution": f"{status.resolution[0]}×{status.resolution[1]}", "fps": f"{status.fps:.1f}",
            "frame_read": "SUCCESS" if status.frame_read_success else "NO FRAME",
            "face": "YES" if status.face_detected else "NO",
            "eyes": f"{'YES' if status.left_eye_detected else 'NO'} / {'YES' if status.right_eye_detected else 'NO'}",
            "left_quality": f"{status.left_eye_quality:.0%}", "right_quality": f"{status.right_eye_quality:.0%}",
            "overall_quality": f"{status.overall_quality:.0%}",
            "openness": f"{status.left_eye_openness} / {status.right_eye_openness}",
            "head_pose": f"{status.head_pose_state} · yaw {status.head_yaw_deg:.1f}° pitch {status.head_pitch_deg:.1f}° roll {status.head_roll_deg:.1f}°" if status.head_yaw_deg is not None else status.head_pose_state,
            "eye_resolution": f"{status.left_eye_pixel_width:.0f} px / {status.right_eye_pixel_width:.0f} px",
            "sharpness": f"{status.left_eye_sharpness:.0f} / {status.right_eye_sharpness:.0f}",
            "lighting": status.lighting_quality, "distance": status.distance_quality,
            "sample_validity": "VALID BINOCULAR SAMPLE" if status.binocular_valid else "INVALID BINOCULAR SAMPLE",
        }
        for key, value in values.items(): self.diagnostics[key].setText(str(value))
        self.explanation.setText(status.quality_explanation or "No quality evidence is available yet.")
        self.diagnostics["overall_quality"].setToolTip(status.quality_explanation)
        self.stop_button.setEnabled(status.connected)
        self.calibration_button.setEnabled(status.connected)

    def set_error(self, message: str) -> None:
        self.status.setText(f"HARDWARE ERROR — {message}")
        self.diagnostics["camera_open"].setText("NO")
        self.diagnostics["frame_read"].setText("FAILED")


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


class NewExperimentPage(QWidget):
    start_requested = Signal(str, object, bool)

    def __init__(self) -> None:
        super().__init__(); layout, root = heading("New Experiment", "Configure a timestamped pre → intervention → post research session.")
        QVBoxLayout(self).addWidget(root); group = QGroupBox("Protocol"); self.form = QFormLayout(group)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.subject = QLineEdit("P-001"); self.subject.setMaxLength(64); self.subject.setToolTip("Coded ID: letters, numbers, period, underscore, or hyphen.")
        self.kind = QComboBox()
        for kind, config in DEFAULT_EXPERIMENTS.items(): self.kind.addItem(config.name, kind.value)
        self.duration = QSpinBox(); self.duration.setRange(2, 3600); self.duration.setSingleStep(1); self.duration.setValue(10); self.duration.setSuffix(" s per phase")
        self.trajectory = QComboBox()
        for trajectory in PursuitTrajectory: self.trajectory.addItem(trajectory.value.title(), trajectory.value)
        self.speed = QDoubleSpinBox(); self.speed.setDecimals(2); self.speed.setRange(.02, 3); self.speed.setSingleStep(.05); self.speed.setValue(.2); self.speed.setSuffix(" Hz")
        self.amplitude = QDoubleSpinBox(); self.amplitude.setDecimals(2); self.amplitude.setRange(.01, .45); self.amplitude.setValue(.35); self.amplitude.setSingleStep(.01)
        self.amplitude.setToolTip("Normalized screen-coordinate half-range: 0.35 moves ±35% of screen width/height around center.")
        self.target_x = QDoubleSpinBox(); self.target_x.setDecimals(2); self.target_x.setRange(.05, .95); self.target_x.setSingleStep(.05); self.target_x.setValue(.5)
        self.target_y = QDoubleSpinBox(); self.target_y.setDecimals(2); self.target_y.setRange(.05, .95); self.target_y.setSingleStep(.05); self.target_y.setValue(.5)
        self.target_size = QSpinBox(); self.target_size.setRange(3, 30); self.target_size.setSingleStep(1); self.target_size.setValue(5); self.target_size.setSuffix(" px radius")
        self.video = QCheckBox("Store camera video (explicit opt-in; recording indicator remains visible)")
        self.form.addRow("Subject identifier", self.subject); self.form.addRow("Experiment", self.kind); self.form.addRow("Duration", self.duration)
        self.form.addRow("Trajectory", self.trajectory); self.form.addRow("Speed", self.speed); self.form.addRow("Amplitude", self.amplitude)
        self.form.addRow("Target X", self.target_x); self.form.addRow("Target Y", self.target_y); self.form.addRow("Target size", self.target_size)
        self.form.addRow("Storage", self.video)
        layout.addWidget(group)
        self.protocol_note = QLabel(); self.protocol_note.setObjectName("Safety"); self.protocol_note.setWordWrap(True); layout.addWidget(self.protocol_note)
        self.start_button = QPushButton("Start controlled session"); self.start_button.setObjectName("Primary"); self.start_button.setMinimumHeight(40)
        self.start_button.clicked.connect(self.emit_start); layout.addWidget(self.start_button); layout.addStretch()
        self.kind.currentIndexChanged.connect(self.update_experiment_fields)
        self.update_experiment_fields()

    def _show_field(self, widget: QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        label = self.form.labelForField(widget)
        if label is not None: label.setVisible(visible)

    def update_experiment_fields(self) -> None:
        kind = ExperimentKind.parse(self.kind.currentData())
        pursuit = kind == ExperimentKind.PURSUIT
        fixation = kind == ExperimentKind.FIXATION
        vergence = kind == ExperimentKind.VERGENCE_PROXY
        self._show_field(self.trajectory, pursuit)
        self._show_field(self.speed, pursuit or vergence)
        self._show_field(self.amplitude, pursuit or vergence)
        for widget in (self.target_x, self.target_y, self.target_size): self._show_field(widget, fixation)
        speed_label = self.form.labelForField(self.speed); amplitude_label = self.form.labelForField(self.amplitude)
        if speed_label: speed_label.setText("Oscillation rate" if vergence else "Speed")
        if amplitude_label: amplitude_label.setText("Screen disparity half-range" if vergence else "Amplitude")
        base = DEFAULT_EXPERIMENTS[kind]
        duration = preference('experiments/fixation_duration') if fixation else preference('experiments/pursuit_duration') if pursuit else int(base.duration_s)
        self.duration.setValue(duration); self.speed.setValue(base.speed_hz); self.amplitude.setValue(base.amplitude)
        if fixation:
            self.protocol_note.setText("Fixation target position is normalized from 0.00 (top/left) to 1.00 (bottom/right). Target size is a pixel radius.")
        elif pursuit:
            self.protocol_note.setText("Pursuit amplitude is normalized screen half-range; for example, 0.35 moves ±35% around screen center.")
        elif vergence:
            self.protocol_note.setText("Preliminary screen vergence proxy only: oscillation rate and normalized horizontal disparity are not physical depth or vergence angle.")
        else:
            self.protocol_note.setText("External near–far uses timed phases and researcher-recorded physical target-distance events; no on-screen motion parameters apply.")

    def build_config(self) -> ExperimentConfig:
        kind = ExperimentKind.parse(self.kind.currentData())
        base = DEFAULT_EXPERIMENTS[kind]
        return ExperimentConfig(
            name=base.name, kind=kind, duration_s=float(self.duration.value()),
            trajectory=PursuitTrajectory.parse(self.trajectory.currentData()),
            speed_hz=float(self.speed.value()), amplitude=float(self.amplitude.value()),
            fixation_target_x=float(self.target_x.value()), fixation_target_y=float(self.target_y.value()),
            target_size_px=int(self.target_size.value()),
        )

    def emit_start(self) -> None:
        try:
            subject_id = validate_subject_identifier(self.subject.text())
            config = self.build_config()
        except (TypeError, ValueError) as exc:
            LOGGER.exception("New Experiment configuration validation failed")
            QMessageBox.warning(self, "Unable to start session", f"Unable to start session because the experiment configuration is invalid.\n\n{exc}")
            return
        self.start_requested.emit(subject_id, config, self.video.isChecked())


class LivePage(QWidget):
    stop_requested = Signal(); marker_requested = Signal(str); distance_requested = Signal(float); researcher_panel_changed = Signal(bool)
    pause_requested = Signal(); abort_requested = Signal(); restart_requested = Signal()

    def __init__(self) -> None:
        super().__init__(); layout, root = heading("Live Session", "Stimulus timing and acquisition use a monotonic clock; every event is also recorded in UTC nanoseconds.")
        QVBoxLayout(self).addWidget(root); top = QHBoxLayout(); self.recording = QLabel("NOT RECORDING"); self.recording.setObjectName("Recording")
        self.elapsed = QLabel("00:00.000"); self.phase = QLabel("Idle"); self.quality = QLabel("Quality —"); top.addWidget(self.recording); top.addWidget(self.phase); top.addStretch(); top.addWidget(self.quality); top.addWidget(self.elapsed); layout.addLayout(top)
        body = QHBoxLayout(); self.canvas = StimulusCanvas(); body.addWidget(self.canvas, 4)
        self.panel = QGroupBox("Researcher panel"); panel = QFormLayout(self.panel)
        self.fps = QLabel("—"); self.conf = QLabel("—"); self.eyes = QLabel("—"); self.coords = QLabel("—"); self.samples = QLabel("0")
        for label, widget in [("FPS", self.fps), ("Confidence", self.conf), ("Both eyes", self.eyes), ("Gaze", self.coords), ("Samples", self.samples)]: panel.addRow(label, widget)
        self.target_readout=QLabel('—');self.left_readout=QLabel('—');self.right_readout=QLabel('—');self.proxy_readout=QLabel('—');self.gaps_readout=QLabel('—')
        for label,w in [('Target',self.target_readout),('Left eye',self.left_readout),('Right eye',self.right_readout),('Vergence proxy',self.proxy_readout),('Frame-ID gaps',self.gaps_readout)]: w.setWordWrap(True);panel.addRow(label,w)
        self.mark_button = QPushButton("Mark event"); self.mark_button.clicked.connect(lambda: self.marker_requested.emit("manual_marker")); panel.addRow(self.mark_button)
        distances = QGridLayout()
        for i, value in enumerate([100, 75, 50, 40, 30, 20, 15, 10]):
            button = QPushButton(f"{value} cm"); button.clicked.connect(lambda checked=False, v=value: self.distance_requested.emit(float(v))); distances.addWidget(button, i // 2, i % 2)
        self.distance_widget=QWidget();self.distance_widget.setLayout(distances);panel.addRow(QLabel("External near–far target distance"));panel.addRow(self.distance_widget); body.addWidget(self.panel, 1); layout.addLayout(body, 1)
        self.phase_progress=QProgressBar();self.phase_progress.setRange(0,1000);layout.addWidget(self.phase_progress)
        self.phase_history=QLabel('No active session.');layout.addWidget(self.phase_history)
        self.live_plot=LivePlot();layout.addWidget(self.live_plot)
        controls = QHBoxLayout(); self.hide_panel = QCheckBox("Hide researcher panel"); self.hide_panel.toggled.connect(self.panel.setHidden)
        self.stop_button = QPushButton("Stop and analyze"); self.stop_button.clicked.connect(self.stop_requested)
        self.pause_button=QPushButton('Pause');self.pause_button.clicked.connect(self.pause_requested)
        self.abort_button=QPushButton('Abort and save');self.abort_button.setObjectName('Danger');self.abort_button.clicked.connect(self.abort_requested)
        self.restart_button=QPushButton('Restart phase');self.restart_button.clicked.connect(self.restart_requested)
        controls.addWidget(self.hide_panel); controls.addStretch()
        for w in (self.pause_button,self.restart_button,self.stop_button,self.abort_button):controls.addWidget(w)
        layout.addLayout(controls);self.set_recording(False)

    def set_recording(self, active: bool, video: bool = False) -> None:
        self.recording.setText("● RECORDING VIDEO + DATA" if active and video else "● RECORDING DATA" if active else "NOT RECORDING")
        for button in (self.pause_button,self.restart_button,self.mark_button,self.stop_button,self.abort_button):
            button.setEnabled(active);button.setToolTip('Start an experiment first.' if not active else '')
        self.distance_widget.setEnabled(active)
        if not active:self.phase_history.setText('No active session.');self.phase.setText('Idle');self.pause_button.setText('Pause')




class PlaceholderPage(QWidget):
    def __init__(self, title: str, body: str) -> None:
        super().__init__(); layout, root = heading(title, body); QVBoxLayout(self).addWidget(root); layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self, data_root: str | Path | None = None) -> None:
        super().__init__(); self.setWindowTitle("Amble Research 0.1"); self.resize(1420, 900); self.setStyleSheet(APP_STYLE)
        self.store = DataStore(data_root or os.getenv("AMBLE_DATA_DIR") or preference('general/data_directory')); self.tracker = SimulatedEyeTracker(); self.tracker.connect(); self.tracker.start_stream()
        self._log_handler = logging.FileHandler(self.store.root / 'amble.log', encoding='utf-8')
        self._log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        logging.getLogger('amble').addHandler(self._log_handler)
        self.protocol = None; self._last_ui = 0; self._last_frame_id = None; self._frame_gaps = 0
        self.calibration = None; self.recorder = None; self.runtime = None; self.config = None; self.session_start = 0; self.phase_start = 0; self.phase_index = 0; self.last_distance = None; self.video_enabled = False; self.pending_marker = ""
        self._tracker_error_shown = False
        central = QWidget(); self.setCentralWidget(central); root = QHBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(210); side = QVBoxLayout(sidebar); side.setContentsMargins(8, 8, 8, 8)
        brand = QLabel("AMBLE\nRESEARCH"); brand.setObjectName("Brand"); side.addWidget(brand)
        self.stack = QStackedWidget(); self.pages = {
            "Dashboard": DashboardPage(self.store), "Subjects": SubjectsPage(self.store), "New Experiment": NewExperimentPage(),
            "Live Session": LivePage(), "Sessions": DashboardPage(self.store), "Analytics": AnalyticsPage(self.store),
            "Raw Data": RawDataPage(self.store), "Calibration": CalibrationPage(), "Hardware": HardwarePage(),
            "Settings": SettingsPage(self.store),
        }
        self.nav_buttons = []
        for name, page in self.pages.items():
            self.stack.addWidget(page); button = QPushButton(name); button.setObjectName("Nav"); button.setCheckable(True); button.clicked.connect(lambda checked=False, n=name: self.navigate(n)); side.addWidget(button); self.nav_buttons.append((name, button))
        side.addStretch(); side.addWidget(QLabel("v0.1.0\nResearch use only")); root.addWidget(sidebar); root.addWidget(self.stack, 1)
        self.pages["Hardware"].connect_requested.connect(self.connect_tracker); self.pages["Hardware"].disconnect_requested.connect(self.disconnect_tracker); self.pages["Hardware"].calibration_requested.connect(lambda: self.navigate("Calibration"))
        self.pages["Hardware"].scan_requested.connect(self.scan_cameras)
        self.pages["Hardware"].threshold_changed.connect(lambda value: self.tracker.set_minimum_quality(value))
        self.pages["Hardware"].eye_range_changed.connect(lambda low, high: self.tracker.set_preferred_eye_width_range(low, high))
        self.pages["Hardware"].overlay.toggled.connect(lambda enabled: self.tracker.set_debug_overlay(enabled))
        self.pages["Hardware"].head_comp.toggled.connect(lambda enabled: self.tracker.set_head_pose_compensation(enabled))
        self.pages["Calibration"].started.connect(self.ensure_streaming); self.pages["Calibration"].completed.connect(self.set_calibration)
        self.pages["New Experiment"].start_requested.connect(self.start_session); self.pages["Live Session"].stop_requested.connect(self.stop_session); self.pages["Live Session"].marker_requested.connect(self.mark_event); self.pages["Live Session"].distance_requested.connect(self.set_distance)
        self.pages["Analytics"].raw_requested.connect(self.show_raw)
        self.pages['Subjects'].session_requested.connect(self.open_stored_session)
        self.pages['Subjects'].changed.connect(self.refresh_subject_views)
        for page in ('Dashboard','Sessions'): self.pages[page].session_requested.connect(lambda sid: self.open_stored_session(sid,'Analytics'))
        self.pages['Settings'].applied.connect(self.apply_settings)
        self.pages['Live Session'].pause_requested.connect(self.toggle_pause)
        self.pages['Live Session'].restart_requested.connect(self.restart_phase)
        self.pages['Live Session'].abort_requested.connect(self.abort_session)
        self.apply_settings()
        self.timer = QTimer(self); self.timer.setInterval(8); self.timer.timeout.connect(self.tick); self.timer.start(); self.navigate("Dashboard")
        exit_action = QAction(self); exit_action.setShortcut(QKeySequence("Ctrl+Q")); exit_action.triggered.connect(self.close); self.addAction(exit_action)
        if preference('general/auto_subject') and preference('general/last_subject'): self.navigate('Subjects')

    def apply_settings(self):
        theme = preference('general/theme')
        if theme == 'system': theme = 'dark' if QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else 'light'
        style = APP_STYLE
        if theme == 'light':
            for dark,light in [('#0f1720','#f0f3f7'),('#111c27','#e6edf4'),('#111c26','#ffffff'),('#162431','#ffffff'),('#172532','#e6edf4'),('#dce5ec','#182b3c'),('#f2f7fa','#102637'),('#91a4b4','#4b6071'),('#cbd8e2','#182b3c')]: style=style.replace(dark,light)
        self.setStyleSheet(style)
        h=self.pages['Hardware']
        low,high=preference('hardware/preferred_eye_width_min_px'),preference('hardware/preferred_eye_width_max_px')
        for widget in (h.quality_threshold,h.eye_width_min,h.eye_width_max):widget.blockSignals(True)
        h.quality_threshold.setValue(preference('hardware/minimum_binocular_quality'))
        h.eye_width_min.setValue(low);h.eye_width_max.setValue(max(low+5,high))
        for widget in (h.quality_threshold,h.eye_width_min,h.eye_width_max):widget.blockSignals(False)
        h._update_range_label()
        camera=preference('hardware/camera_index')
        if h.camera.findData(camera)<0:h.camera.addItem(f'Camera {camera}',camera)
        h.camera.setCurrentIndex(h.camera.findData(camera));h.backend.setCurrentIndex(h.backend.findData(preference('hardware/backend')))
        h.overlay.setChecked(preference('research/overlay'));h.diagnostics_box.setVisible(preference('research/diagnostics'))
        if not self.recorder:
            self.tracker.set_minimum_quality(h.quality_threshold.value()/100)
            self.tracker.set_preferred_eye_width_range(*h.preferred_eye_width_range())
            self.tracker.set_eye_quality(preference('hardware/minimum_eye_quality')/100)
        self.pages['New Experiment'].update_experiment_fields()
        self.pages['Live Session'].live_plot.window_s=preference('analytics/window_seconds')
        logging.getLogger('amble').setLevel(preference('research/log_level'))
        self.pages['Analytics'].refresh()

    def refresh_subject_views(self):
        for name in ('Dashboard','Sessions'):self.pages[name].refresh()
        self.pages['Analytics'].reload_sessions();self.pages['Raw Data'].reload_sessions()

    def open_stored_session(self,sid,page):
        self.navigate(page)
        if page=='Analytics':self.pages[page].reload_sessions(sid)
        else:self.pages[page].open_session(sid)

    def navigate(self, name: str) -> None:
        current = self.stack.currentWidget()
        hardware = self.pages["Hardware"]
        if current is hardware and name != "Hardware" and isinstance(self.tracker, WebcamEyeTracker) and not self.recorder:
            self.tracker.disconnect()
            hardware.preview.clear(); hardware.preview.setText("Camera preview inactive — webcam released")
        self.stack.setCurrentWidget(self.pages[name])
        for n, button in self.nav_buttons: button.setChecked(n == name)
        page = self.pages[name]
        if hasattr(page, "refresh") and name in ["Dashboard", "Subjects", "Sessions"]: page.refresh()
        if hasattr(page, "reload_sessions") and name in ["Analytics", "Raw Data"]: page.reload_sessions()
        if name == 'Settings': page.reload()

    def connect_tracker(self, backend: str, device) -> None:
        if self.recorder:
            QMessageBox.warning(self,'Recording active','Stop recording before changing the tracking source.');return
        candidate = None
        try:
            self.tracker.disconnect()
            if backend == "simulated": candidate = SimulatedEyeTracker()
            elif backend == "openface": candidate = OpenFaceEyeTracker()
            else: candidate = WebcamEyeTracker()
            self.tracker = candidate
            self.tracker.connect(device); self.tracker.start_stream()
            if isinstance(self.tracker,WebcamEyeTracker):self.tracker.request_camera_format(preference('camera/resolution'),preference('camera/fps'))
            if backend != "webcam":
                preview = self.pages["Hardware"].preview
                preview.clear(); preview.setText("Simulator active — no camera preview" if backend == "simulated" else "OpenFace external acquisition active")
            self.tracker.set_head_pose_compensation(self.pages["Hardware"].head_comp.isChecked())
            self.tracker.set_debug_overlay(self.pages["Hardware"].overlay.isChecked())
            self.tracker.set_minimum_quality(self.pages["Hardware"].quality_threshold.value() / 100)
            self.tracker.set_preferred_eye_width_range(*self.pages["Hardware"].preferred_eye_width_range())
            self.tracker.set_eye_quality(preference('hardware/minimum_eye_quality')/100)
            self._tracker_error_shown = False
            status = self.tracker.status(); self.pages["Hardware"].update_status(status)
        except Exception as exc:
            if candidate is not None:
                self.tracker = candidate
                try: self.tracker.disconnect()
                except Exception: pass
            self.pages["Hardware"].set_error(str(exc))
            QMessageBox.critical(
                self, "Camera access failed",
                f"{type(exc).__name__}: {exc}\n\nNo simulator was substituted. Correct the hardware issue or click 'Use Simulator Instead' explicitly."
            )

    def scan_cameras(self) -> None:
        if self.recorder:
            QMessageBox.warning(self, "Recording active", "Stop the active session before scanning camera devices.")
            return
        if isinstance(self.tracker, WebcamEyeTracker):
            self.tracker.disconnect()
            preview = self.pages["Hardware"].preview
            preview.clear(); preview.setText("Camera released for device scan")
        self.pages["Hardware"].scan()

    def disconnect_tracker(self) -> None:
        if self.recorder: QMessageBox.warning(self, "Recording active", "Stop the session before disconnecting acquisition."); return
        self.tracker.disconnect(); self.pages["Hardware"].preview.clear(); self.pages["Hardware"].preview.setText("Camera preview inactive")
        self.pages["Hardware"].update_status(self.tracker.status())

    def ensure_streaming(self) -> None:
        status = self.tracker.status()
        if not status.connected: self.tracker.connect()
        if not status.streaming: self.tracker.start_stream()

    def set_calibration(self, result) -> None:
        result.tracker_type = self.tracker.tracker_type; self.calibration = result

    def validate_session_request(self, subject_id: str, config: ExperimentConfig) -> str:
        subject_id = validate_subject_identifier(subject_id)
        if self.recorder is not None:
            raise ValueError("A session is already recording.")
        if not isinstance(config, ExperimentConfig):
            raise TypeError("The experiment configuration has the wrong type.")
        if any(row['subject_id']==subject_id and row['archived'] for row in self.store.list_subjects(True)):
            raise ValueError('Restore this archived subject before recording another session.')
        config.to_dict()  # exercises the typed serialization boundary before storage changes
        if not self.store.root.is_dir() or not os.access(self.store.root, os.W_OK):
            raise ValueError("The configured data-storage folder is not writable.")
        return subject_id

    def start_session(self, subject_id: str, config: ExperimentConfig, video: bool) -> None:
        try:
            subject_id = self.validate_session_request(subject_id, config)
            self.ensure_streaming(); status = self.tracker.status()
            if not status.connected or not status.streaming:
                raise RuntimeError("The selected tracking backend is not available.")
            self.config = config
            self.config.quality_threshold = self.pages["Hardware"].quality_threshold.value() / 100
            self.tracker.set_minimum_quality(self.config.quality_threshold)
            eye_min, eye_max = self.pages["Hardware"].preferred_eye_width_range()
            self.tracker.set_preferred_eye_width_range(eye_min, eye_max)
            self.tracker.set_eye_quality(preference('hardware/minimum_eye_quality')/100)
            self.runtime = ExperimentRuntime(config); self.video_enabled = bool(video and self.tracker.tracker_type.startswith("webcam"))
            self.pages["Live Session"].canvas.set_target_size(config.target_size_px)
            self.recorder = self.store.create_session(
                subject_id, config, self.tracker.tracker_type, self.calibration,
                {
                    "camera_resolution": list(status.resolution), "measured_fps_at_start": status.fps,
                    "video_requested": video, "preferred_eye_width_min_px": eye_min,
                    "preferred_eye_width_max_px": eye_max, "quality_threshold": self.config.quality_threshold,
                    "tracker_backend": self.tracker.tracker_type,
                    'minimum_eye_quality': preference('hardware/minimum_eye_quality')/100,
                    'requested_resolution':preference('camera/resolution'),'requested_fps':preference('camera/fps'),
                    'countdown_s':preference('experiments/countdown'),'phase_transition_delay_s':preference('experiments/transition_delay'),
                },
                video_enabled=self.video_enabled,
            )
            if video and not self.video_enabled:
                QMessageBox.information(self, "Video not available", "Camera video was requested, but the active simulator has no camera frames. Tracking data will still be recorded.")
            self.session_start = self.phase_start = time.perf_counter(); self.phase_index = 0; self.last_distance = None
            self.protocol=ProtocolClock(config.phases,config.duration_s,countdown=preference('experiments/countdown'),transition_delay=preference('experiments/transition_delay'))
            self._phase_onset_pending=True
            self._last_frame_id=None;self._frame_gaps=0
            live=self.pages['Live Session'];live.live_plot.points.clear();live.pause_button.setText('Pause')
            live.distance_widget.setEnabled(config.kind==ExperimentKind.EXTERNAL_NEAR_FAR)
            QSettings().setValue('general/last_subject',subject_id)
            self.set_recording_controls(True)
            self.pending_marker = "session_started"
            self.recorder.event(time.time_ns(), "session_started", config.phases[0], config.to_dict()); self.pages["Live Session"].set_recording(True, self.video_enabled); self.navigate("Live Session")
            self.pages['Live Session'].distance_widget.setEnabled(config.kind==ExperimentKind.EXTERNAL_NEAR_FAR)
        except Exception as exc:
            LOGGER.exception("Unable to start controlled session")
            QMessageBox.critical(
                self, "Unable to start session",
                f"Unable to start session because the experiment configuration or tracking setup is invalid.\n\n{exc}",
            )

    def tick(self) -> None:
        state = None
        if self.recorder and self.protocol and not self.protocol.paused and not self.protocol.remaining_delay():
            state=self.runtime.state_at(self.protocol.elapsed(),self.protocol.phase)
            self.tracker.set_target(state.x,state.y)
        calibration = self.pages["Calibration"]
        if calibration.timer.isActive():
            self.tracker.set_target(*calibration.canvas.target)
        try:
            sample = self.tracker.get_sample()
        except Exception as exc:
            try: self.tracker.disconnect()
            except Exception: pass
            hardware = self.pages["Hardware"]; hardware.set_error(str(exc)); hardware.preview.clear(); hardware.preview.setText("Camera stream stopped after a frame-read error")
            if not self._tracker_error_shown:
                self._tracker_error_shown = True
                QMessageBox.critical(self, "Camera stream stopped", f"{type(exc).__name__}: {exc}\n\nNo simulator was substituted.")
            return
        status = self.tracker.status(); hardware = self.pages["Hardware"]
        render = time.perf_counter()-self._last_ui >= .05
        if render:
            hardware.update_status(status); self._last_ui=time.perf_counter()
            if self.recorder:hardware.calibration_button.setEnabled(False);hardware.calibration_button.setToolTip('Stop the current session before calibration.')
        frame = self.tracker.get_preview_frame()
        if render and frame is not None and cv2 is not None and self.stack.currentWidget() is hardware and hardware.preview.isVisible() and hardware.preview.width() > 1 and hardware.preview.height() > 1:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB); h, w, channels = rgb.shape; image = QImage(rgb.data, w, h, channels * w, QImage.Format_RGB888).copy(); hardware.preview.setPixmap(QPixmap.fromImage(image).scaled(hardware.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if sample is not None and calibration.timer.isActive(): calibration.accept_sample(sample)
        if not self.recorder or sample is None: return
        live=self.pages['Live Session']
        if self.protocol.paused:
            live.quality.setText('PAUSED — acquisition active; experimental rows suspended');return
        if self.protocol.remaining_delay():
            live.phase.setText('COUNTDOWN');live.phase_history.setText(f'{self.protocol.phase.upper()} starts in {self.protocol.remaining_delay():.1f} s')
            live.quality.setText('Acquisition active; experimental rows begin at phase onset');return
        if self._phase_onset_pending:
            self.recorder.event(time.time_ns(),'phase_onset',self.protocol.phase,{'attempt':self.protocol.attempt})
            self._phase_onset_pending=False
        now = time.perf_counter(); phase = self.protocol.phase; elapsed_phase=self.protocol.elapsed()
        if state is None:state=self.runtime.state_at(elapsed_phase,phase)
        sample.experiment_id = self.config.kind.value; sample.trial_id = f'{phase}_{self.protocol.attempt}'; sample.phase_attempt=self.protocol.attempt; sample.target_x = state.x; sample.target_y = state.y; sample.experiment_phase = phase; sample.target_distance_cm = self.last_distance
        sample.event_marker = self.pending_marker; self.pending_marker = ""
        self.recorder.append(sample)
        if self.video_enabled and frame is not None:
            self.recorder.append_video_frame(frame, sample.camera_fps or 30.0)
        live = self.pages["Live Session"]; live.canvas.set_target(state.x, state.y); live.canvas.add_gaze(sample.binocular_gaze_x, sample.binocular_gaze_y)
        live.elapsed.setText(self._format_time(now - self.session_start)); live.phase.setText(phase.upper()); live.fps.setText(f"{sample.camera_fps:.1f}")
        confidence = sample.overall_quality; live.conf.setText(f"L {sample.left_eye_quality:.0%} · R {sample.right_eye_quality:.0%} · overall {confidence:.0%}")
        live.eyes.setText("VALID BINOCULAR" if sample.binocular_valid else "INVALID"); live.coords.setText(f"{sample.binocular_gaze_x:.3f}, {sample.binocular_gaze_y:.3f}" if sample.binocular_gaze_x is not None else "—"); live.samples.setText(f"{self.recorder.sample_count:,}"); live.quality.setText("Quality OK" if sample.binocular_valid else sample.tracking_guidance.upper())
        live.target_readout.setText(f'{state.x:.3f}, {state.y:.3f}')
        for eye,label in [('left',live.left_readout),('right',live.right_readout)]:
            x,y=getattr(sample,f'{eye}_gaze_x'),getattr(sample,f'{eye}_gaze_y')
            xy=f'{x:.3f}, {y:.3f}' if x is not None and y is not None else 'Unavailable'
            label.setText(f"{xy}\n{getattr(sample,eye+'_eye_quality'):.0%} · {getattr(sample,eye+'_eye_openness')} · {'valid' if getattr(sample,eye+'_eye_valid') else 'invalid'}")
        proxy=sample.right_gaze_x-sample.left_gaze_x if sample.right_gaze_x is not None and sample.left_gaze_x is not None else None
        live.proxy_readout.setText(f'{proxy:.4f} normalized R−L' if proxy is not None else 'Unavailable')
        if self._last_frame_id is not None:self._frame_gaps+=max(0,sample.frame_number-self._last_frame_id-1)
        self._last_frame_id=sample.frame_number;live.gaps_readout.setText(str(self._frame_gaps)+' recorded ID gaps')
        live.live_plot.append(now-self.session_start,state.x,sample.left_gaze_x,sample.right_gaze_x)
        live.phase_progress.setValue(int(1000*min(1,elapsed_phase/self.config.duration_s)))
        live.phase_progress.setFormat(f'{phase.upper()} · {elapsed_phase:.1f} / {self.config.duration_s:g} s · attempt {self.protocol.attempt}')
        live.phase_history.setText('   →   '.join(f'{p.upper()} '+('complete' if i<self.phase_index else 'active' if i==self.phase_index else 'not started') for i,p in enumerate(self.config.phases)))
        if state.finished: self.advance_phase()

    @staticmethod
    def _format_time(seconds: float) -> str:
        minutes = int(seconds // 60); return f"{minutes:02d}:{seconds - minutes * 60:06.3f}"

    def advance_phase(self) -> None:
        phase = self.config.phases[self.phase_index]; self.recorder.event(time.time_ns(), "phase_completed", phase)
        more=self.protocol.advance();self.phase_index=self.protocol.index
        if not more: self.stop_session(); return
        self.phase_start = time.perf_counter(); self.pending_marker = "phase_started"; self.recorder.event(time.time_ns(), "phase_started", self.config.phases[self.phase_index])
        self._phase_onset_pending=True

    def mark_event(self, name: str) -> None:
        if self.recorder:
            self.pending_marker = name
            self.recorder.event(time.time_ns(), name, self.config.phases[self.phase_index])

    def set_recording_controls(self,active):
        h=self.pages['Hardware']
        for widget in (h.backend,h.camera,h.scan_button,h.connect_button,h.simulator_button,h.quality_threshold,h.eye_width_min,h.eye_width_max,h.distance_slider,h.distance_preset,self.pages['Settings'].save_button,self.pages['Settings'].restore_button,self.pages['Subjects'].rename_button,self.pages['Subjects'].archive_button,self.pages['Calibration']):
            widget.setEnabled(not active)
            widget.setToolTip('Stop the active session before changing acquisition or study settings.' if active else '')

    def toggle_pause(self):
        if not self.recorder:return
        if self.protocol.paused:self.protocol.resume();event='session_resumed';label='Pause'
        else:self.protocol.pause();event='session_paused';label='Resume'
        self.recorder.event(time.time_ns(),event,self.protocol.phase,{'phase_elapsed_s':self.protocol.elapsed(),'attempt':self.protocol.attempt})
        self.pages['Live Session'].pause_button.setText(label)
        self._last_frame_id=None

    def restart_phase(self):
        if not self.recorder:return
        if QMessageBox.question(self,'Restart phase','Restart this phase? Earlier rows remain with their original attempt number. Analytics will use the newest attempt.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        self.protocol.restart();self.phase_start=time.perf_counter()
        self._phase_onset_pending=True
        self.recorder.event(time.time_ns(),'phase_restarted',self.protocol.phase,{'attempt':self.protocol.attempt})

    def abort_session(self):
        if not self.recorder:return
        if QMessageBox.question(self,'Abort session','Abort and save this partial session with state ABORTED?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:self.stop_session('aborted')

    def set_distance(self, distance: float) -> None:
        self.last_distance = distance
        if self.recorder:
            self.pending_marker = f"physical_target_distance_{distance:g}cm"
            self.recorder.event(time.time_ns(), "physical_target_distance", self.config.phases[self.phase_index], {"distance_cm": distance})

    def stop_session(self, state='complete') -> None:
        if not self.recorder: return
        session_id = self.recorder.session_id
        try:
            self.recorder.event(time.time_ns(), 'session_aborted' if state=='aborted' else 'session_stopped', self.config.phases[min(self.phase_index, len(self.config.phases)-1)])
            self.recorder.close(state); frame = latest_attempts(self.store.load_samples(session_id)); metrics = analyze_session(frame, self.config.kind.value, self.config.quality_threshold)
            calibration_error = self.calibration.average_error_px if self.calibration else None
            metrics.append({"phase": "all", "name": "calibration_error", "value": calibration_error, "unit": "px",
                            "kind": "direct measurement", "quality_ok": bool(self.calibration and self.calibration.quality in {"good", "acceptable"}),
                            "details": {} if self.calibration else {"reason": "Calibration not performed"}})
            self.store.save_metrics(session_id, metrics)
        except Exception as exc: QMessageBox.critical(self, "Finalize session", str(exc))
        finally:
            self.recorder = None; self.set_recording_controls(False); self.pages["Live Session"].set_recording(False); self.navigate("Analytics"); self.pages["Analytics"].reload_sessions(session_id)

    def show_raw(self, session_id: str, selection) -> None:
        self.navigate('Raw Data');self.pages['Raw Data'].open_session(session_id,selection)

    def closeEvent(self, event) -> None:
        if self.recorder:
            answer = QMessageBox.question(self, "Recording active", "Stop, save, and exit?")
            if answer != QMessageBox.Yes: event.ignore(); return
            self.stop_session()
        self.timer.stop();self.tracker.disconnect();logging.getLogger('amble').removeHandler(self._log_handler);self._log_handler.close();event.accept()
