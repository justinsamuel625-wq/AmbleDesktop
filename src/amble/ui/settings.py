from pathlib import Path
from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,QScrollArea,
    QLabel,QComboBox,QSpinBox,QCheckBox,QLineEdit,QPushButton,QFileDialog,QMessageBox)
from amble.preferences import SPECS, preference, restore_defaults

class SettingsPage(QWidget):
    applied=Signal()
    def __init__(self,store):
        super().__init__(); self.store=store; self.controls={}
        layout=QVBoxLayout(self); title=QLabel('Settings'); title.setObjectName('PageTitle'); layout.addWidget(title)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); content=QWidget(); body=QVBoxLayout(content); scroll.setWidget(content); layout.addWidget(scroll,1)
        groups={
            'General':[('general/theme','Theme'),('general/data_directory','Data directory (next launch)'),('general/auto_subject','Reopen last selected subject')],
            'Data':[('data/export_format','Default filtered export format')],
            'Tracking quality':[('hardware/minimum_binocular_quality','Minimum binocular quality (%)'),('hardware/minimum_eye_quality','Minimum per-eye quality (%)'),('hardware/preferred_eye_width_min_px','Preferred eye width minimum (px)'),('hardware/preferred_eye_width_max_px','Preferred eye width maximum (px)')],
            'Camera':[('hardware/camera_index','Preferred camera index'),('hardware/backend','Preferred tracker (explicit Connect required)'),('camera/resolution','Requested resolution (on next Connect)'),('camera/fps','Requested FPS (on next Connect)')],
            'Experiments':[('experiments/fixation_duration','Default fixation phase duration (s)'),('experiments/pursuit_duration','Default pursuit phase duration (s)'),('experiments/countdown','Start countdown (s)'),('experiments/transition_delay','Phase transition delay (s)')],
            'Analytics':[('analytics/window_seconds','Initial chart window / live history (s)'),('analytics/show_invalid','Show invalid samples in charts'),('analytics/smoothing','Smooth display traces only'),('analytics/smoothing_window','Display smoothing window (samples)')],
            'Research / developer':[('research/overlay','Landmark debug overlay'),('research/diagnostics','Show full technical Hardware diagnostics'),('research/log_level','Log level')],
        }
        for group,fields in groups.items():
            box=QGroupBox(group); form=QFormLayout(box); form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for key,label in fields:
                default,low,high=SPECS[key]
                if isinstance(default,bool): w=QCheckBox()
                elif isinstance(default,int):w=QSpinBox();w.setRange(low,high)
                elif isinstance(low,tuple):w=QComboBox();w.addItems(low)
                else:w=QLineEdit()
                self.controls[key]=w; form.addRow(label,w)
                if key=='general/data_directory':
                    browse=QPushButton('Choose directory');browse.clicked.connect(self.choose_directory);form.addRow('',browse)
            if group=='Data':
                note=QLabel('Raw rows are autosaved during acquisition. Raw data and opted-in video are retained until you manage them explicitly. Destructive subject actions always require confirmation.');note.setWordWrap(True);form.addRow(note)
            if group=='Camera':
                note=QLabel('Acquisition uses the camera’s negotiated resolution/FPS, shown in Hardware. Changing preview size affects display only.');note.setWordWrap(True);form.addRow(note)
            if group=='Tracking quality':
                note=QLabel('Strict binocular validity requires both measurable open eyes to pass the per-eye gate, plus the overall binocular gate. Invalid rows remain available for audit.');note.setWordWrap(True);form.addRow(note)
            body.addWidget(box)
        self.log_path=QLabel(f'Application log: {store.root / "amble.log"}');self.log_path.setWordWrap(True);body.addWidget(self.log_path)
        buttons=QHBoxLayout();self.save_button=QPushButton('Apply settings');self.restore_button=QPushButton('Restore Defaults');buttons.addWidget(self.save_button);buttons.addWidget(self.restore_button);buttons.addStretch();layout.addLayout(buttons)
        self.message=QLabel('');self.message.setWordWrap(True);layout.addWidget(self.message)
        self.save_button.clicked.connect(self.save);self.restore_button.clicked.connect(self.restore);self.reload()

    def reload(self):
        for key,w in self.controls.items():
            value=preference(key)
            if isinstance(w,QCheckBox):w.setChecked(value)
            elif isinstance(w,QSpinBox):w.setValue(value)
            elif isinstance(w,QComboBox):w.setCurrentText(value)
            else:w.setText(value)

    def choose_directory(self):
        path=QFileDialog.getExistingDirectory(self,'Default data directory')
        if path:self.controls['general/data_directory'].setText(path)

    def save(self):
        if self.controls['hardware/preferred_eye_width_max_px'].value()<=self.controls['hardware/preferred_eye_width_min_px'].value():
            self.message.setText('Preferred maximum must be greater than minimum.');return
        path=Path(self.controls['general/data_directory'].text()).expanduser()
        if not path.is_absolute():self.message.setText('Choose an absolute data-directory path.');return
        settings=QSettings()
        for key,w in self.controls.items():
            value=w.isChecked() if isinstance(w,QCheckBox) else w.value() if isinstance(w,QSpinBox) else w.currentText() if isinstance(w,QComboBox) else w.text().strip()
            settings.setValue(key,value)
        settings.sync();self.applied.emit();self.message.setText('Settings saved. The data directory changes on next launch; existing data is not moved.')

    def restore(self):
        if QMessageBox.question(self,'Restore Defaults','Restore application preferences? Research data will remain intact.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            restore_defaults();self.reload();self.applied.emit();self.message.setText('Default preferences restored.')
