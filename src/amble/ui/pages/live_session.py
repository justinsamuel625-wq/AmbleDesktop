"""Live recording and researcher-control page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from amble.ui.components import LivePlot, StimulusCanvas
from amble.ui.pages.common import heading


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



__all__ = ["LivePage"]
