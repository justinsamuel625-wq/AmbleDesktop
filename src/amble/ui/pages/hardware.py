"""Hardware acquisition, preview, and diagnostics page."""

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from amble.core.preferences import preference
from amble.tracking import enumerate_cameras, validate_opencv
from amble.ui.components import CameraView


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



__all__ = ["HardwarePage"]

