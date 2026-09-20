"""Shared persisted-data queries used by Analytics and Raw Data."""
import json
import numpy as np
import pandas as pd
from amble.analysis import analyze_session

def truth(series):
    return series.fillna(False).astype(str).str.lower().isin(['true', '1', '1.0'])

def validity(frame, key='binocular_valid'):
    if key not in frame: key = 'valid'
    return truth(frame[key]) if key in frame else pd.Series(False, index=frame.index)

def elapsed(frame):
    if frame.empty: return pd.Series(dtype=float, index=frame.index)
    return (pd.to_numeric(frame.timestamp_ns) - frame.timestamp_ns.min()) / 1e9

def filter_rows(frame, phase='all', valid='all', query='', start=None, end=None, columns=None, attempt=None):
    mask = pd.Series(True, index=frame.index)
    if phase != 'all': mask &= frame.experiment_phase.astype(str).eq(phase)
    if valid == 'valid': mask &= validity(frame)
    elif valid == 'invalid': mask &= ~validity(frame)
    elif valid == 'left': mask &= validity(frame, 'left_eye_valid')
    elif valid == 'right': mask &= validity(frame, 'right_eye_valid')
    t = elapsed(frame)
    if start is not None: mask &= t >= start
    if end is not None: mask &= t <= end
    if attempt is not None and 'phase_attempt' in frame: mask &= frame.phase_attempt.eq(attempt)
    result = frame.loc[mask]
    if query.strip():
        fields = [c for c in (columns or list(frame.columns)) if c in frame]
        hits = result[fields].astype(str).apply(lambda s: s.str.contains(query.strip(), case=False, regex=False)).any(axis=1)
        result = result.loc[hits]
    return result

def latest_attempts(frame):
    if 'phase_attempt' not in frame or frame.empty: return frame
    maximum = frame.groupby('experiment_phase').phase_attempt.transform('max')
    return frame.loc[frame.phase_attempt.eq(maximum)]

def quality_summary(frame):
    n = len(frame)
    def mean(key, fallback=None):
        values = pd.to_numeric(frame.get(key, frame.get(fallback, pd.Series(dtype=float))), errors='coerce')
        return float(values.mean()) if values.notna().any() else None
    valid = int(validity(frame).sum())
    t = elapsed(frame)
    delta = np.diff(np.sort(frame.timestamp_ns.to_numpy(dtype=np.int64))) / 1e9 if n else []
    positive = np.asarray(delta)[np.asarray(delta) > 0]
    # This measures gaps in recorded source identifiers, not sensor-level drops.
    ids = pd.to_numeric(frame.get('frame_number', pd.Series(dtype=float)), errors='coerce').dropna()
    span = int(ids.max() - ids.min() + 1) if len(ids) else 0
    return dict(count=n, valid=valid, invalid=n-valid, valid_pct=100*valid/n if n else 0,
                quality=mean('overall_quality', 'left_confidence'), left=mean('left_eye_quality', 'left_confidence'),
                right=mean('right_eye_quality', 'right_confidence'), duration=float(t.max()) if n else 0,
                fps=float(1/np.median(positive)) if len(positive) else None,
                gaps_pct=100*max(0, span-len(ids.unique()))/span if span else None,
                status='INSUFFICIENT DATA' if valid < 30 or valid/max(n, 1) < .6 else 'CAUTION' if valid/n < .85 else 'GOOD')

METRICS = {
    'fixation': ['bcea_68', 'rms_gaze_error', 'fixation_drift', 'left_right_error_asymmetry'],
    'smooth_pursuit': ['pursuit_rmse', 'pursuit_lag', 'pursuit_gain', 'left_right_error_asymmetry'],
    'vergence_proxy': ['vergence_proxy_mean', 'left_right_error_asymmetry', 'rms_gaze_error'],
    'external_near_far': ['vergence_proxy_mean', 'left_right_error_asymmetry'],
}

def comparisons(frame, kind, threshold=.7):
    frame = latest_attempts(frame)
    metrics = analyze_session(frame, kind, threshold)
    indexed = {(m['phase'], m['name']): m for m in metrics}
    result = []
    for name in METRICS.get(kind, ['rms_gaze_error']):
        row = {'name': name, 'unit': '', 'reasons': {}}
        for phase in ('pre', 'intervention', 'post'):
            metric = indexed.get((phase, name))
            value = metric.get('value') if metric and metric['quality_ok'] else None
            if value is not None and not np.isfinite(value): value = None
            row[phase] = value
            if metric: row['unit'] = metric['unit']
            if value is None:
                subset = frame.loc[frame.experiment_phase.eq(phase)]
                summary = quality_summary(subset)
                row['reasons'][phase] = ('No samples in this phase' if not len(subset) else
                    f"{summary['valid']} / {len(subset)} valid rows; metric needs adequate valid coverage, sufficient samples and nonconstant target for pursuit gain/lag")
        row['delta'] = row['post'] - row['pre'] if row['pre'] is not None and row['post'] is not None else None
        row['percent'] = 100*row['delta']/abs(row['pre']) if row['delta'] is not None and abs(row['pre']) > 1e-12 else None
        result.append(row)
    return result

def session_trends(store, session, metric_name):
    result = []
    for item in reversed(store.list_sessions()):
        if (item['subject_id'], item['experiment_kind']) != (session['subject_id'], session['experiment_kind']): continue
        if item['state'] != 'complete': continue
        try:
            threshold = json.loads(item['config_json']).get('quality_threshold', .7)
            row = next((m for m in comparisons(store.load_samples(item['session_id']), item['experiment_kind'], threshold) if m['name'] == metric_name), None)
            if row and row['post'] is not None:
                result.append(dict(session_id=item['session_id'], date=item['created_at'], value=row['post']))
        except (OSError, ValueError, KeyError): continue
    return result
