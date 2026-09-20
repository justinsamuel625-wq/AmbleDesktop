from pathlib import Path
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QDoubleSpinBox, QTableView, QFileDialog, QMessageBox, QMenu)
from amble.preferences import preference
from amble.research import filter_rows, elapsed

DEFAULT_COLUMNS = ['timestamp_ns', 'experiment_phase', 'phase_attempt', 'target_x', 'target_y',
    'left_gaze_x', 'left_gaze_y', 'right_gaze_x', 'right_gaze_y', 'left_eye_quality',
    'right_eye_quality', 'binocular_valid', 'left_eye_openness', 'right_eye_openness',
    'head_yaw_deg', 'head_pitch_deg', 'camera_fps']

class FrameModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent); self.frame = pd.DataFrame(); self.sort_column = None; self.ascending = True
    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.frame)
    def columnCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.frame.columns)
    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role in (Qt.DisplayRole, Qt.ToolTipRole):
            value = self.frame.iloc[index.row(), index.column()]
            return '' if pd.isna(value) else str(value)
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return str(self.frame.columns[section]) if orientation == Qt.Horizontal else str(self.frame.index[section] + 1)
    def set_frame(self, frame):
        self.beginResetModel(); self.frame = frame.copy()
        if self.sort_column in self.frame: self.frame = self.frame.sort_values(self.sort_column, ascending=self.ascending, kind='stable', na_position='last')
        self.endResetModel()
    def sort(self, column, order=Qt.AscendingOrder):
        if column < 0 or column >= len(self.frame.columns): return
        self.sort_column = self.frame.columns[column]; self.ascending = order == Qt.AscendingOrder
        self.set_frame(self.frame)

class RawDataPage(QWidget):
    def __init__(self, store):
        super().__init__(); self.store = store; self.frame = None; self.session_id = ''; self.context = {}; self.columns = []
        layout = QVBoxLayout(self)
        title = QLabel('Raw Data Explorer'); title.setObjectName('PageTitle'); layout.addWidget(title)
        row = QHBoxLayout(); self.sessions = QComboBox(); self.load_button = QPushButton('Load')
        row.addWidget(self.sessions, 1); row.addWidget(self.load_button); layout.addLayout(row)
        filters = QHBoxLayout(); self.phase = QComboBox(); self.phase.addItem('All phases', 'all')
        self.valid = QComboBox()
        for label, value in [('All samples','all'), ('Valid binocular','valid'), ('Invalid binocular','invalid'), ('Left eye valid','left'), ('Right eye valid','right')]: self.valid.addItem(label, value)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search visible columns')
        for w in (self.phase, self.valid, self.search): filters.addWidget(w)
        layout.addLayout(filters)
        times = QHBoxLayout(); self.start = QDoubleSpinBox(); self.end = QDoubleSpinBox()
        for w in (self.start, self.end): w.setRange(0, 1e9); w.setDecimals(3); w.setSuffix(' s')
        self.reset_button = QPushButton('Reset Filters'); self.columns_button = QPushButton('Visible columns')
        for w in (QLabel('Elapsed start'), self.start, QLabel('End'), self.end, self.columns_button, self.reset_button): times.addWidget(w)
        layout.addLayout(times)
        self.info = QLabel('Select a session and click Load.'); self.info.setWordWrap(True); layout.addWidget(self.info)
        self.context_label = QLabel(''); self.context_label.setWordWrap(True); layout.addWidget(self.context_label)
        self.model = FrameModel(self); self.table = QTableView(); self.table.setModel(self.model); self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True); self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table, 1)
        exports = QHBoxLayout(); self.export_button = QPushButton('Export filtered view'); self.full_button = QPushButton('Export full session')
        exports.addWidget(self.export_button); exports.addWidget(self.full_button); exports.addStretch(); layout.addLayout(exports)
        self.load_button.clicked.connect(self.load); self.reset_button.clicked.connect(self.reset_filters)
        self.export_button.clicked.connect(self.export); self.full_button.clicked.connect(self.export_full)
        self.sessions.currentIndexChanged.connect(self.clear_dataset)
        for signal in (self.phase.currentIndexChanged, self.valid.currentIndexChanged, self.search.textChanged, self.start.valueChanged, self.end.valueChanged): signal.connect(self.apply_filters)
        self.clear_dataset(); self.reload_sessions()

    def clear_dataset(self):
        self.frame = None; self.session_id = ''; self.context = {}; self.model.set_frame(pd.DataFrame())
        self.info.setText('Select a session and click Load.'); self.context_label.clear()
        for w in (self.export_button, self.full_button, self.reset_button, self.columns_button):
            w.setEnabled(False); w.setToolTip('Load a session first.')

    def reload_sessions(self, select_id=None):
        selected = select_id or self.sessions.currentData()
        self.sessions.blockSignals(True); self.sessions.clear()
        for row in self.store.list_sessions(): self.sessions.addItem(f"{row['subject_id']} · {row['experiment_kind']} · {row['created_at'][:19]} · {row['state']}", row['session_id'])
        index = self.sessions.findData(selected); self.sessions.setCurrentIndex(index if index >= 0 else 0); self.sessions.blockSignals(False)
        if self.session_id and self.session_id != self.sessions.currentData(): self.clear_dataset()
        self.load_button.setEnabled(self.sessions.count() > 0)

    def load(self):
        sid = self.sessions.currentData()
        self.clear_dataset()
        if not sid: return
        try: frame = self.store.load_samples(sid)
        except Exception as exc: self.info.setText(f'Unable to load this dataset: {exc}'); return
        self.frame = frame; self.session_id = sid; self.columns = [c for c in DEFAULT_COLUMNS if c in frame]
        self.phase.blockSignals(True); self.phase.clear(); self.phase.addItem('All phases', 'all')
        for phase in frame.experiment_phase.dropna().unique(): self.phase.addItem(str(phase), str(phase))
        self.phase.blockSignals(False)
        menu = QMenu(self.columns_button)
        for column in frame.columns:
            action = QAction(column, menu); action.setCheckable(True); action.setChecked(column in self.columns)
            action.toggled.connect(lambda checked, col=column: self.toggle_column(col, checked)); menu.addAction(action)
        self.columns_button.setMenu(menu)
        for w in (self.export_button, self.full_button, self.reset_button, self.columns_button): w.setEnabled(True); w.setToolTip('')
        self.reset_filters()

    def toggle_column(self, column, checked):
        if checked and column not in self.columns: self.columns.append(column)
        elif not checked and column in self.columns: self.columns.remove(column)
        self.apply_filters()

    def reset_filters(self):
        self.context = {}; self.context_label.clear()
        for w in (self.phase, self.valid, self.search, self.start, self.end): w.blockSignals(True)
        self.phase.setCurrentIndex(0); self.valid.setCurrentIndex(0); self.search.clear(); self.start.setValue(0)
        self.end.setValue(float(elapsed(self.frame).max()) + .001 if self.frame is not None and len(self.frame) else 0)
        for w in (self.phase, self.valid, self.search, self.start, self.end): w.blockSignals(False)
        self.apply_filters()

    def filtered_frame(self):
        if self.frame is None: return None
        return filter_rows(self.frame, self.phase.currentData(), self.valid.currentData(), self.search.text(),
                           self.start.value(), self.end.value(), self.columns, self.context.get('attempt'))

    def apply_filters(self):
        frame = self.filtered_frame()
        if frame is None: return
        self.model.set_frame(frame[self.columns])
        self.info.setText(f'Rows shown: {len(frame):,} / {len(self.frame):,} · {self.store.raw_path(self.session_id)}')

    def open_session(self, sid, context=None):
        self.reload_sessions(sid); self.load()
        if self.frame is None: return
        self.context = context or {}
        self.phase.setCurrentIndex(max(0, self.phase.findData(self.context.get('phase', 'all'))))
        self.valid.setCurrentIndex(max(0, self.valid.findData(self.context.get('valid', 'all'))))
        if self.context.get('start') is not None: self.start.setValue(max(0, self.context['start']))
        if self.context.get('end') is not None: self.end.setValue(max(0, self.context['end']))
        self.context_label.setText('Chart / metric context: ' + self.context.get('metric', 'All raw rows') + (' · latest phase attempt' if self.context.get('attempt') else ''))
        self.apply_filters()

    def export_to(self, path):
        # Model holds every filtered row, selected columns, and current numeric sort.
        if Path(path).suffix.lower() == '.parquet': self.model.frame.to_parquet(path, index=False)
        else: self.model.frame.to_csv(path, index=False)

    def export(self):
        if self.frame is None: return
        extension = 'parquet' if preference('data/export_format') == 'Parquet' else 'csv'
        path, _ = QFileDialog.getSaveFileName(self, 'Export filtered view', f'{self.session_id}_filtered.{extension}', 'CSV (*.csv);;Parquet (*.parquet)')
        if path:
            try: self.export_to(path)
            except Exception as exc: QMessageBox.warning(self, 'Export failed', str(exc))

    def export_full(self):
        if not self.session_id: return
        folder = QFileDialog.getExistingDirectory(self, 'Export full session folder')
        if folder:
            try: self.store.research_export(self.session_id, folder)
            except Exception as exc: QMessageBox.warning(self, 'Export failed', str(exc))
