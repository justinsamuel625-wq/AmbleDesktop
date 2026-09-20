"""Experiment configuration page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from amble.core.domain import (
    ExperimentConfig, ExperimentKind, PursuitTrajectory,
    validate_subject_identifier,
)
from amble.core.preferences import preference
from amble.experiments import DEFAULT_EXPERIMENTS
from amble.ui.pages.common import LOGGER, heading


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



__all__ = ["NewExperimentPage"]

