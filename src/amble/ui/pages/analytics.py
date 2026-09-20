import html
import json
import tempfile
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton, QFileDialog, QMessageBox
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from amble.analysis.research import comparisons, elapsed, quality_summary, session_trends, validity
from amble.core.preferences import preference

def fmt(value, percent=False):
    if value is None or not np.isfinite(value): return 'Unavailable'
    return f'{value*100:.1f}%' if percent else f'{value:.4g}'

class RowBridge(QObject):
    requested = Signal(str)
    @Slot(str)
    def openRows(self, context): self.requested.emit(context)

class AnalyticsPage(QWidget):
    raw_requested = Signal(str, object)
    def __init__(self, store):
        super().__init__(); self.store = store; self._html = ''; self._contexts = {}
        self._temp = tempfile.TemporaryDirectory(prefix='amble_charts_'); self.folder = Path(self._temp.name)
        (self.folder / 'plotly.min.js').write_text(get_plotlyjs(), encoding='utf-8')
        layout = QVBoxLayout(self); title = QLabel('Session Analytics'); title.setObjectName('PageTitle'); layout.addWidget(title)
        controls = QHBoxLayout(); self.sessions = QComboBox(); controls.addWidget(self.sessions, 1)
        self.raw_button = QPushButton('View underlying rows'); self.export_button = QPushButton('Export report HTML'); self.full_button = QPushButton('Export full session')
        for w in (self.raw_button, self.export_button, self.full_button): controls.addWidget(w)
        layout.addLayout(controls)
        self.chart = QWebEngineView(); layout.addWidget(self.chart, 1)
        self.bridge = RowBridge(self); self.channel = QWebChannel(self.chart.page()); self.channel.registerObject('rows', self.bridge); self.chart.page().setWebChannel(self.channel)
        self.bridge.requested.connect(self._open_context)
        self.sessions.currentIndexChanged.connect(self.refresh)
        self.raw_button.clicked.connect(lambda: self.raw_requested.emit(self.sessions.currentData() or '', {}))
        self.export_button.clicked.connect(self.export_chart); self.full_button.clicked.connect(self.research_export)
        self.reload_sessions()

    def _open_context(self, payload):
        try:
            selected = json.loads(payload); key = selected.get('key', '')
            context = dict(self._contexts.get(key, {}))
            sid = context.pop('session_id', self.sessions.currentData())
            if selected.get('start') is not None: context['start'] = float(selected['start'])
            if selected.get('end') is not None: context['end'] = float(selected['end'])
            self.raw_requested.emit(sid, context)
        except (ValueError, TypeError): return

    def reload_sessions(self, select_id=None):
        selected = select_id or self.sessions.currentData()
        self.sessions.blockSignals(True); self.sessions.clear()
        for row in self.store.list_sessions(): self.sessions.addItem(f"{row['subject_id']} · {row['experiment_kind']} · {row['created_at'][:19]} · {row['state']}", row['session_id'])
        self.sessions.setCurrentIndex(max(0, self.sessions.findData(selected))); self.sessions.blockSignals(False); self.refresh()

    def _show(self, content):
        self._html = """<!doctype html><html><head><meta charset="utf-8"><script src="plotly.min.js"></script>
        <script src="qrc:///qtwebchannel/qwebchannel.js"></script><style>
        body{background:#0f1720;color:#dce5ec;font:14px 'Segoe UI',sans-serif;margin:20px} h2{font-size:21px;margin:26px 0 12px}
        .cards{display:flex;flex-wrap:wrap;gap:10px}.card{background:#172532;border:1px solid #34495c;border-radius:7px;padding:14px;flex:1;min-width:150px}
        small{color:#a6b8c6}b{font-size:18px}table{width:100%;border-collapse:collapse}td,th{padding:10px;text-align:left;border-bottom:1px solid #34495c}
        button{background:#2c6f9f;color:white;padding:9px 14px;border:0;border-radius:4px;cursor:pointer}.notice{padding:14px;background:#202f3e;border-radius:6px}
        .chart{height:320px} .section{margin-bottom:22px} .why{color:#e9c27b}
        </style></head><body>""" + content + """<script>
        let bridge=null; if(window.qt)new QWebChannel(qt.webChannelTransport,c=>bridge=c.objects.rows);
        function rows(key,id){let p={key:key};let graph=id?document.getElementById(id):null;
        if(graph&&graph._fullLayout&&graph._fullLayout.xaxis){let r=graph._fullLayout.xaxis.range;p.start=r[0];p.end=r[1];}
        if(bridge)bridge.openRows(JSON.stringify(p));else alert('Open this report in Amble to inspect the stored rows.');}
        </script></body></html>"""
        path = self.folder / 'report.html'; path.write_text(self._html, encoding='utf-8'); self.chart.load(QUrl.fromLocalFile(str(path)))

    def _plot(self, fig, key, title, context, time_axis=False):
        self._contexts[key] = context
        fig.update_layout(template='plotly_dark', paper_bgcolor='#0f1720', plot_bgcolor='#111c26',
            margin=dict(l=65,r=20,t=30,b=65), height=320, legend=dict(orientation='h'), hovermode='x unified')
        if time_axis:
            fig.update_xaxes(title='Session elapsed seconds', rangeslider_visible=True, rangeslider_thickness=.12)
            window = preference('analytics/window_seconds')
            fig.update_xaxes(range=[0, window])
        div = fig.to_html(full_html=False, include_plotlyjs=False, div_id=key, config={'responsive':True, 'displaylogo':False, 'scrollZoom':True, 'modeBarButtonsToRemove':['sendChartToCloud']})
        arg = f"'{key}'" if time_axis else 'null'
        return f'<section class="section"><h2>{html.escape(title)}</h2>{div}<button onclick="rows(\'{key}\',{arg})">View underlying rows</button></section>'

    def refresh(self):
        sid = self.sessions.currentData(); self._contexts = {}
        for b in (self.raw_button, self.export_button, self.full_button): b.setEnabled(bool(sid)); b.setToolTip('Select a recorded session.' if not sid else '')
        if not sid: self._show('<h2>No sessions recorded yet</h2><p>Record a session to review quality, phase changes and eye behavior.</p>'); return
        session = self.store.session(sid)
        try:
            frame = self.store.load_samples(sid)
            metadata = json.loads((Path(session['session_dir'])/'metadata.json').read_text(encoding='utf-8'))
        except Exception as exc: self._show('<h2>Dataset unavailable</h2><p>'+html.escape(str(exc))+'</p>'); return
        q = quality_summary(frame); threshold = json.loads(session['config_json']).get('quality_threshold', .7)
        def cards(items):
            return '<div class="cards">'+''.join(f'<div class="card"><small>{html.escape(k)}</small><br><b>{html.escape(str(v))}</b></div>' for k,v in items)+'</div>'
        calibration = json.loads(session['calibration_json']) if session.get('calibration_json') else None
        cal = 'Not performed'
        if calibration:
            errors=[p['binocular_error_px'] for p in calibration.get('points',[]) if p['valid']]
            cal=f'{len(errors)} valid points · mean {np.mean(errors):.1f} px' if errors else 'No valid calibration points'
        body='<h2>What happened in this session?</h2>'+cards([
            ('Subject', session['subject_id']),('Experiment', session['experiment_kind']),('Recorded', session['created_at'][:19]),
            ('Duration',f"{q['duration']:.1f} s"),('Tracker',session['tracker_type']),('Camera resolution',metadata.get('camera_resolution') or 'Not recorded'),
            ('Calibration',cal),('Session state',session['state'])])
        body+='<h2>Is the data usable?</h2>'+cards([('Quality status',q['status']),('Valid binocular',f"{q['valid_pct']:.1f}%"),
            ('Average quality',fmt(q['quality'],True)),('Left quality',fmt(q['left'],True)),('Right quality',fmt(q['right'],True)),
            ('Invalid rows',q['invalid']),('Sampling rate',fmt(q['fps'])+' Hz'),('Recorded frame-ID gaps',fmt(q['gaps_pct'])+'%')])
        body+='<p class="notice">Frame-ID gaps are an estimate from recorded identifiers; hardware-level drops are unavailable. Pauses and restarts can also create gaps. Phase comparisons use the latest attempt of each phase. Changes describe observations and do not establish an intervention effect.</p>'
        if q['valid'] == 0: body+=f"<p class='why'>{q['valid_pct']:.0f}% valid samples — no behavioral metrics can be calculated. Inspect invalid rows for eye openness, resolution, lighting and quality rejection reasons.</p>"
        rows = comparisons(frame,session['experiment_kind'],threshold)
        body+='<h2>PRE → intervention → POST</h2><table><tr><th>Metric / units</th><th>PRE</th><th>Intervention</th><th>POST</th><th>Delta</th><th>Change %</th></tr>'
        for row in rows:
            body+='<tr><td>'+html.escape(row['name'].replace('_',' ')+' · '+row['unit'])+'</td>'
            for phase in ('pre','intervention','post'):
                key=f"metric_{row['name']}_{phase}"; subset=frame.loc[frame.experiment_phase.eq(phase)]
                attempt=int(subset.phase_attempt.max()) if 'phase_attempt' in subset and len(subset) else None
                self._contexts[key]={'phase':phase,'metric':row['name'],'attempt':attempt}
                reason=html.escape(row['reasons'].get(phase,''))
                value=fmt(row[phase]) if row[phase] is not None else 'Insufficient data'
                body+=f'<td title="{reason}">{value}<br><small>{reason}</small><br><button onclick="rows(\'{key}\',null)">Rows</button></td>'
            body+=f"<td>{fmt(row['delta'])}</td><td>{fmt(row['percent'])}</td></tr>"
        body+='</table>'
        # Separate metric plots retain units; missing measurements are never drawn as zero.
        for i,row in enumerate(rows):
            if all(row[p] is None for p in ('pre','intervention','post')): continue
            fig=go.Figure(go.Bar(x=['pre','intervention','post'], y=[row[p] for p in ('pre','intervention','post')], marker_color=['#56a9d6','#e0b45b','#58c98d']))
            fig.update_yaxes(title=row['unit'])
            body+=self._plot(fig,f'comparison_{i}',row['name'].replace('_',' '),{'metric':row['name']})
        valid_frame=frame if preference('analytics/show_invalid') else frame.loc[validity(frame)]
        t=elapsed(frame).reindex(valid_frame.index)
        def series(column):
            y=valid_frame[column]
            if preference('analytics/smoothing') and column not in ('left_eye_openness','right_eye_openness'):
                y=y.rolling(preference('analytics/smoothing_window'),min_periods=1).mean()
            return y
        groups=[('Eye position and target', ['target_x','target_y','left_gaze_x','left_gaze_y','right_gaze_x','right_gaze_y','binocular_gaze_x','binocular_gaze_y']),
                ('Left vs right tracking quality',['left_eye_quality','right_eye_quality','overall_quality']),
                ('Eye openness',['left_eye_openness','right_eye_openness']),
                ('Eye resolution (px)',['left_eye_pixel_width','right_eye_pixel_width']),
                ('Head pose (degrees)',['head_yaw_deg','head_pitch_deg','head_roll_deg'])]
        body+='<h2>Left and right eyes over time</h2><p>Zoom or select a range with the range slider; View underlying rows carries that displayed time range into Raw Data. '+('Display smoothing enabled; raw rows and metrics remain unchanged.' if preference('analytics/smoothing') else 'Traces display recorded values.')+'</p>'
        for i,(title,columns) in enumerate(groups):
            fig=go.Figure()
            for col in columns:
                if col in valid_frame and valid_frame[col].notna().any(): fig.add_scatter(x=t,y=series(col),name=col,mode='lines',connectgaps=False)
            if fig.data: body+=self._plot(fig,f'time_{i}',title,{'metric':title,'valid':'all' if preference('analytics/show_invalid') else 'valid'},True)
        if {'left_gaze_x','right_gaze_x'} <= set(valid_frame):
            fig=go.Figure(go.Scatter(x=t,y=valid_frame.right_gaze_x-valid_frame.left_gaze_x,name='R − L horizontal gaze',mode='lines'))
            body+=self._plot(fig,'vergence','Vergence proxy (normalized horizontal difference)',{'metric':'vergence proxy','valid':'all' if preference('analytics/show_invalid') else 'valid'},True)
        trend=session_trends(self.store,session,rows[0]['name']) if rows else []
        if len(trend)>1:
            fig=go.Figure(go.Scatter(x=[x['date'] for x in trend],y=[x['value'] for x in trend],mode='lines+markers',name='POST '+rows[0]['name']))
            body+=self._plot(fig,'trend','Prior completed sessions: '+rows[0]['name'],{'metric':'longitudinal trend'})
            for i,item in enumerate(trend):
                key=f'trend_session_{i}'; self._contexts[key]={'session_id':item['session_id'],'phase':'post','metric':rows[0]['name']}
                body+=f'<button onclick="rows(\'{key}\',null)">Rows: {html.escape(item["date"][:19])}</button> '
        else: body+='<h2>Session trend</h2><p>At least two completed sessions with valid POST metrics for this subject and experiment are needed.</p>'
        self._show(body)

    def export_chart(self):
        if not self._html: return
        path,_=QFileDialog.getSaveFileName(self,'Export report','amble_report.html','HTML (*.html)')
        if path:
            Path(path).write_text(self._html.replace('<script src="plotly.min.js"></script>','<script>'+get_plotlyjs()+'</script>'),encoding='utf-8')

    def research_export(self):
        sid=self.sessions.currentData()
        if not sid: return
        folder=QFileDialog.getExistingDirectory(self,'Export full session')
        if folder:
            try: self.store.research_export(sid,folder)
            except Exception as exc: QMessageBox.warning(self,'Export failed',str(exc))
