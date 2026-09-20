import json
import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QMessageBox
from amble.analysis.research import comparisons, filter_rows, quality_summary, session_trends
from amble.core.domain import EyeSample, ExperimentConfig, ExperimentKind
from amble.core.preferences import preference, restore_defaults
from amble.core.session_control import ProtocolClock
from amble.storage.store import DataStore
from amble.ui.main_window import MainWindow, HardwarePage
from amble.ui.pages.raw_data import RawDataPage
from amble.ui.pages.subjects import SubjectsPage

@pytest.fixture(autouse=True)
def preferences_scope(tmp_path, monkeypatch):
    settings=QSettings(str(tmp_path/'prefs.ini'),QSettings.IniFormat)
    for module in (
        'amble.core.preferences', 'amble.ui.main_window',
        'amble.ui.pages.settings', 'amble.ui.pages.subjects',
        'amble.ui.pages.hardware',
    ):
        monkeypatch.setattr(module+'.QSettings',lambda:settings)
    return settings

def record(store, subject='P-001', invalid=False, offset=0):
    rec=store.create_session(subject,ExperimentConfig('Fixation',ExperimentKind.FIXATION),'simulated')
    for phase_no,phase in enumerate(('pre','intervention','post')):
        for i in range(40):
            x=.5+.01*np.sin(i)+.005*phase_no
            rec.append(EyeSample(timestamp_ns=1_000_000_000+offset+(phase_no*40+i)*20_000_000,
                frame_number=phase_no*40+i,experiment_phase=phase,target_x=.5,target_y=.5,
                left_gaze_x=x-.002,right_gaze_x=x+.002,left_gaze_y=.5,right_gaze_y=.5,
                binocular_gaze_x=x,binocular_gaze_y=.5,left_confidence=.9,right_confidence=.9,
                valid=not invalid,binocular_valid=not invalid,left_eye_valid=not invalid,right_eye_valid=not invalid,
                left_eye_quality=.9,right_eye_quality=.9,overall_quality=.9,left_eye_openness='OPEN',right_eye_openness='OPEN'))
    rec.close();return rec.session_id

def test_subject_archive_counts_rename_and_safe_delete(tmp_path):
    store=DataStore(tmp_path/'data');sid=record(store)
    assert store.list_subjects()[0]['session_count']==1
    with pytest.raises(ValueError,match='Archive'):store.delete_empty_subject('P-001')
    store.archive_subject('P-001');assert store.list_subjects()==[]
    assert len(store.list_sessions())==1
    store.archive_subject('P-001',False);store.rename_subject('P-001','P-NEW')
    assert store.session(sid)['subject_id']=='P-NEW'
    assert json.loads((store.sessions_dir/sid/'metadata.json').read_text())['subject_id']=='P-NEW'
    store.ensure_subject('P-EMPTY');store.delete_empty_subject('P-EMPTY');assert len(store.list_subjects())==1

def test_subject_ui_select_history_and_confirmation(qtbot,tmp_path,monkeypatch):
    store=DataStore(tmp_path/'data');sid=record(store);page=SubjectsPage(store);qtbot.addWidget(page)
    page.table.selectRow(0);assert page.selected_id=='P-001';assert page.history.rowCount()==1
    page.history.selectRow(0)
    with qtbot.waitSignal(page.session_requested) as signal:page.raw_button.click()
    assert signal.args==[sid,'Raw Data']
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.No)
    page.archive_button.click();assert len(store.list_subjects())==1
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    page.archive_button.click();assert store.list_subjects()==[]
    store.ensure_subject('EMPTY');page.refresh();page.table.selectRow(0)
    page.delete_button.click();assert store.list_subjects()==[]

def test_comparison_invalid_state_and_trend(tmp_path):
    store=DataStore(tmp_path/'data');sid=record(store);frame=store.load_samples(sid)
    result=comparisons(frame,'fixation');rms=next(x for x in result if x['name']=='rms_gaze_error')
    assert rms['post']>rms['pre'];assert rms['delta']==pytest.approx(rms['post']-rms['pre'])
    assert quality_summary(frame)['status']=='GOOD'
    record(store);trend=session_trends(store,store.session(sid),'rms_gaze_error');assert len(trend)==2
    invalid=store.load_samples(record(store,'P-BAD',True))
    assert quality_summary(invalid)['valid_pct']==0
    bad=comparisons(invalid,'fixation');assert all(row['pre'] is None for row in bad)
    assert '0 / 40' in bad[0]['reasons']['pre']

def test_raw_filters_numeric_sort_columns_and_exact_export(qtbot,tmp_path):
    store=DataStore(tmp_path/'data');sid=record(store);page=RawDataPage(store);qtbot.addWidget(page)
    page.open_session(sid);assert page.model.rowCount()==120
    page.phase.setCurrentIndex(page.phase.findData('pre'));assert page.model.rowCount()==40
    page.valid.setCurrentIndex(page.valid.findData('invalid'));assert page.model.rowCount()==0
    page.valid.setCurrentIndex(0);page.start.setValue(.2);page.end.setValue(.4)
    assert page.model.rowCount()==11
    page.search.setText('not-in-any-column');assert page.model.rowCount()==0
    page.search.clear();page.model.sort(page.columns.index('timestamp_ns'),Qt.DescendingOrder)
    assert page.model.frame.timestamp_ns.is_monotonic_decreasing
    page.toggle_column('target_y',False);path=tmp_path/'filtered.csv';page.export_to(path)
    exported=pd.read_csv(path);assert len(exported)==11;assert 'target_y' not in exported
    assert exported.timestamp_ns.tolist()==page.model.frame.timestamp_ns.tolist()
    page.reset_button.click();assert page.model.rowCount()==120
    page.open_session(sid,{'phase':'post','start':1.8,'end':2.0,'metric':'rms_gaze_error'})
    assert page.model.rowCount()==11;assert page.model.frame.experiment_phase.eq('post').all()

def test_all_validity_filters_and_search_columns(tmp_path):
    store=DataStore(tmp_path/'data');frame=store.load_samples(record(store))
    frame.loc[0,'binocular_valid']=False;frame.loc[1,'left_eye_valid']=False;frame.loc[2,'right_eye_valid']=False
    assert len(filter_rows(frame,valid='invalid'))==1
    assert len(filter_rows(frame,valid='left'))==119
    assert len(filter_rows(frame,valid='right'))==119
    assert len(filter_rows(frame,query='post',columns=['target_x']))==0
    assert len(filter_rows(frame,query='post',columns=['experiment_phase']))==40

def test_clock_pause_resume_restart_and_phases():
    now=[0.];clock=ProtocolClock(['pre','post'],10,lambda:now[0])
    now[0]=3;clock.pause();now[0]=20;assert clock.elapsed()==3
    clock.resume();now[0]=22;assert clock.elapsed()==5
    clock.restart();assert clock.attempt==2;assert clock.elapsed()==0
    assert clock.advance();assert clock.phase=='post';assert clock.attempt==1
    assert not clock.advance()

def test_live_pause_marker_restart_abort_persist_events(qtbot,tmp_path,monkeypatch):
    w=MainWindow(tmp_path/'data');qtbot.addWidget(w);w.timer.stop()
    w.start_session('P-LIVE',ExperimentConfig('Fixation',ExperimentKind.FIXATION),False)
    sid=w.recorder.session_id;w.tick();n=w.recorder.sample_count
    w.pages['Live Session'].pause_button.click();assert w.protocol.paused
    qtbot.wait(20);w.tick();assert w.recorder.sample_count==n
    w.pages['Live Session'].mark_button.click()
    w.pages['Live Session'].pause_button.click();assert not w.protocol.paused
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    w.pages['Live Session'].restart_button.click();assert w.protocol.attempt==2
    qtbot.wait(20);w.tick();w.pages['Live Session'].abort_button.click()
    assert w.recorder is None;assert w.store.session(sid)['state']=='aborted'
    events=pd.read_csv(w.store.sessions_dir/sid/'events.csv')
    assert {'session_paused','manual_marker','session_resumed','phase_restarted','session_aborted'}<=set(events.event)
    assert events.timestamp_ns.is_monotonic_increasing
    assert json.loads((w.store.sessions_dir/sid/'metadata.json').read_text())['state']=='aborted'
    assert w.store.load_samples(sid).phase_attempt.max()==2
    w.close()

def test_settings_apply_restore_and_dependents(qtbot,tmp_path,preferences_scope,monkeypatch):
    w=MainWindow(tmp_path/'data');qtbot.addWidget(w);page=w.pages['Settings']
    page.controls['experiments/fixation_duration'].setValue(33)
    page.controls['hardware/minimum_binocular_quality'].setValue(81)
    page.controls['data/export_format'].setCurrentText('Parquet');page.save_button.click()
    assert preference('experiments/fixation_duration')==33
    assert w.pages['New Experiment'].duration.value()==33
    assert w.pages['Hardware'].quality_threshold.value()==81
    assert w.tracker._quality_threshold==.81
    assert preference('data/export_format')=='Parquet'
    page.reload();assert page.controls['experiments/fixation_duration'].value()==33
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes);page.restore_button.click()
    assert w.pages['New Experiment'].duration.value()==10
    preferences_scope.setValue('experiments/fixation_duration','broken');assert preference('experiments/fixation_duration')==10
    w.close()

def test_hardware_scroll_reachable_all_modes_and_drag_persistence(qtbot,preferences_scope):
    page=HardwarePage();qtbot.addWidget(page);page.resize(900,650);page.show()
    for mode in ('expanded','medium','collapsed'):
        page.set_preview_mode(mode);qtbot.wait(10)
        scroll=page.scroll.verticalScrollBar();assert scroll.maximum()>0
        scroll.setValue(scroll.maximum());assert scroll.value()==scroll.maximum()
    page.set_preview_mode('expanded');page.splitter.setSizes([300,431]);page._splitter_moved()
    sizes=page.splitter.sizes();assert sizes[0]>80
    assert preferences_scope.value('hardware/preview_splitter_sizes')==','.join(str(s) for s in sizes)
    other=HardwarePage();qtbot.addWidget(other);other.resize(900,650);other.show();qtbot.wait(10)
    assert abs(other.splitter.sizes()[0]-sizes[0])<10

def test_analytics_chart_to_raw_context(qtbot,tmp_path):
    w=MainWindow(tmp_path/'data');qtbot.addWidget(w);sid=record(w.store)
    w.pages['Analytics'].reload_sessions(sid);page=w.pages['Analytics']
    assert 'What happened in this session?' in page._html
    assert '0% valid samples' not in page._html
    page._open_context(json.dumps({'key':'time_0','start':.2,'end':.4}))
    raw=w.pages['Raw Data'];assert raw.session_id==sid;assert raw.model.rowCount()==11
    assert 'Eye position' in raw.context_label.text()
    w.close()
