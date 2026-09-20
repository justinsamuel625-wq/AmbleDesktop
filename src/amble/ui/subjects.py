import json
from PySide6.QtCore import Signal, QSettings
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLineEdit,QLabel,
    QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QMessageBox,QInputDialog,QCheckBox)
from amble.preferences import preference

class SubjectsPage(QWidget):
    session_requested=Signal(str, str)
    changed=Signal()
    def __init__(self,store):
        super().__init__(); self.store=store; self.selected_id=None; self.rows=[]; self.history_rows=[]
        layout=QVBoxLayout(self); title=QLabel('Subjects'); title.setObjectName('PageTitle'); layout.addWidget(title)
        row=QHBoxLayout(); self.subject_id=QLineEdit(); self.subject_id.setPlaceholderText('Coded identifier, e.g. P-001')
        self.add_button=QPushButton('Add subject'); self.show_archived=QCheckBox('Include archived')
        row.addWidget(self.subject_id,1); row.addWidget(self.add_button); row.addWidget(self.show_archived); layout.addLayout(row)
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['Subject','Created','Sessions','Most recent','Status'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.table,1)
        actions=QHBoxLayout(); self.rename_button=QPushButton('Rename identifier'); self.archive_button=QPushButton('Archive subject'); self.delete_button=QPushButton('Delete empty subject')
        for b in (self.rename_button,self.archive_button,self.delete_button): actions.addWidget(b)
        actions.addStretch(); layout.addLayout(actions)
        self.details=QLabel('Select a subject to view its history.'); self.details.setWordWrap(True); layout.addWidget(self.details)
        self.history=QTableWidget(0,6); self.history.setHorizontalHeaderLabels(['Date','Experiment','Valid samples','Tracker','Duration','State'])
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows); self.history.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers); self.history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.history,1)
        open_row=QHBoxLayout(); self.analytics_button=QPushButton('Open session / analytics'); self.raw_button=QPushButton('Open raw data')
        open_row.addWidget(self.analytics_button); open_row.addWidget(self.raw_button); open_row.addStretch(); layout.addLayout(open_row)
        self.add_button.clicked.connect(self.add_subject); self.show_archived.toggled.connect(self.refresh); self.table.itemSelectionChanged.connect(self.select_subject)
        self.rename_button.clicked.connect(self.rename); self.archive_button.clicked.connect(self.archive); self.delete_button.clicked.connect(self.delete)
        self.history.itemSelectionChanged.connect(self.update_actions)
        self.analytics_button.clicked.connect(lambda:self.open_history('Analytics')); self.raw_button.clicked.connect(lambda:self.open_history('Raw Data'))
        self.history.doubleClicked.connect(lambda:self.open_history('Analytics')); self.refresh()

    def refresh(self):
        selected=self.selected_id or (preference('general/last_subject') if preference('general/auto_subject') else '')
        self.rows=self.store.list_subjects(self.show_archived.isChecked()); self.table.blockSignals(True); self.table.setRowCount(len(self.rows))
        for r,item in enumerate(self.rows):
            for c,value in enumerate([item['subject_id'],item['created_at'][:19],item['session_count'],item['most_recent_session'] or '—','Archived' if item['archived'] else 'Active']):
                self.table.setItem(r,c,QTableWidgetItem(str(value)))
        self.table.clearSelection(); self.table.blockSignals(False); self.selected_id=None
        for i,item in enumerate(self.rows):
            if item['subject_id']==selected: self.table.selectRow(i); break
        self.select_subject()

    def add_subject(self):
        try:
            value=self.subject_id.text().strip(); self.store.ensure_subject(value); self.selected_id=value
            self.subject_id.clear(); self.refresh(); self.changed.emit()
        except ValueError as exc: QMessageBox.warning(self,'Subject',str(exc))

    def select_subject(self):
        chosen=self.table.selectionModel().selectedRows()
        self.selected_id=self.rows[chosen[0].row()]['subject_id'] if chosen else None
        self.history_rows=[s for s in self.store.list_sessions() if s['subject_id']==self.selected_id]
        self.history.setRowCount(len(self.history_rows))
        for r,item in enumerate(self.history_rows):
            n=item['sample_count']; config=json.loads(item['config_json']); duration=config['duration_s']*len(config['phases'])
            if item.get('ended_at'):
                from datetime import datetime
                duration=(datetime.fromisoformat(item['ended_at'])-datetime.fromisoformat(item['created_at'])).total_seconds()
            for c,value in enumerate([item['created_at'][:19],item['experiment_kind'],f"{100*item['valid_sample_count']/n:.1f}%" if n else 'No samples',item['tracker_type'],f'{duration:.1f} s',item['state']]):
                self.history.setItem(r,c,QTableWidgetItem(str(value)))
        if self.selected_id:
            QSettings().setValue('general/last_subject',self.selected_id)
            row=next(s for s in self.rows if s['subject_id']==self.selected_id)
            experiments=', '.join(sorted({s['experiment_kind'] for s in self.history_rows})) or 'None'
            self.details.setText(f"{self.selected_id} · created {row['created_at'][:19]} · {len(self.history_rows)} sessions\nExperiments: {experiments}"+('\nNo sessions recorded yet.' if not self.history_rows else ''))
            self.archive_button.setText('Restore subject' if row['archived'] else 'Archive subject')
        else: self.details.setText('Select a subject to view its history.' if self.rows else 'No subjects yet. Add a coded identifier above.')
        self.update_actions()

    def update_actions(self):
        for b in (self.rename_button,self.archive_button,self.delete_button): b.setEnabled(bool(self.selected_id)); b.setToolTip('Select a subject first.' if not self.selected_id else '')
        self.delete_button.setEnabled(bool(self.selected_id) and not self.history_rows)
        if self.history_rows: self.delete_button.setToolTip('Subjects with sessions can be archived. Their research data is preserved.')
        selected=bool(self.history.selectionModel().selectedRows())
        for b in (self.analytics_button,self.raw_button): b.setEnabled(selected); b.setToolTip('Select a session from history.' if not selected else '')

    def open_history(self,page):
        selected=self.history.selectionModel().selectedRows()
        if selected: self.session_requested.emit(self.history_rows[selected[0].row()]['session_id'],page)

    def rename(self):
        if not self.selected_id:return
        value,ok=QInputDialog.getText(self,'Rename coded identifier','New coded identifier:',text=self.selected_id)
        if ok:
            try: self.store.rename_subject(self.selected_id,value); self.selected_id=value.strip(); self.refresh(); self.changed.emit()
            except Exception as exc: QMessageBox.warning(self,'Rename failed',str(exc))

    def archive(self):
        if not self.selected_id:return
        current=next(r for r in self.rows if r['subject_id']==self.selected_id); archive=not current['archived']
        action='Archive' if archive else 'Restore'
        message=f"{action} subject {self.selected_id}?\n{len(self.history_rows)} associated sessions will be preserved. Archiving hides the subject from the active list; it can be restored."
        if QMessageBox.question(self,action+' subject',message,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.store.archive_subject(self.selected_id,archive); self.refresh(); self.changed.emit()

    def delete(self):
        if not self.selected_id:return
        message=f'Delete subject {self.selected_id}?\n0 sessions affected. Only this empty subject entry will be deleted.'
        if QMessageBox.question(self,'Delete empty subject',message,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            try:self.store.delete_empty_subject(self.selected_id); self.selected_id=None; self.refresh(); self.changed.emit()
            except ValueError as exc:QMessageBox.warning(self,'Delete blocked',str(exc))
