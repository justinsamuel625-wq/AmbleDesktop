"""Top-level application shell and session coordinator."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from amble.analysis import analyze_session
from amble.analysis.research import latest_attempts
from amble.core.domain import ExperimentConfig, ExperimentKind, validate_subject_identifier
from amble.core.preferences import preference
from amble.core.session_control import ProtocolClock
from amble.experiments import ExperimentRuntime
from amble.storage import DataStore
from amble.tracking import (
    OpenFaceEyeTracker, SimulatedEyeTracker, WebcamEyeTracker,
)
from amble.ui.pages import (
    AnalyticsPage, CalibrationPage, DashboardPage, HardwarePage, LivePage,
    NewExperimentPage, RawDataPage, SettingsPage, SubjectsPage,
)
from amble.ui.theme import APP_STYLE

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


LOGGER = logging.getLogger(__name__)


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
