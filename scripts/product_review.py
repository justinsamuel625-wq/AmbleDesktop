"""Launch an isolated synthetic-data workspace for interactive product verification."""
import math
from pathlib import Path
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from amble.core.domain import EyeSample, ExperimentConfig, ExperimentKind
from amble.storage.store import DataStore
from amble.ui.main_window import MainWindow

app=QApplication([]);app.setApplicationName('Amble Product QA');app.setOrganizationName('Amble Research QA')
root=Path(__file__).resolve().parents[1]/'.hardware-product-review'
store=DataStore(root)
if not store.list_sessions():
    for run in range(2):
        config=ExperimentConfig('Fixation Stability',ExperimentKind.FIXATION)
        rec=store.create_session('QA-SYNTHETIC',config,'simulated',camera_settings={'camera_resolution':[640,480]})
        for p,phase in enumerate(config.phases):
            for i in range(300):
                f=p*300+i;x=.5+(.02-.003*p-.002*run)*math.sin(i*.21);y=.5+.012*math.cos(i*.13)
                valid=i%29!=0;q=.93 if valid else .25
                rec.append(EyeSample(timestamp_ns=1_790_000_000_000_000_000+run*60_000_000_000+f*33_333_333,
                    frame_number=f,experiment_phase=phase,target_x=.5,target_y=.5,left_gaze_x=x-.003,right_gaze_x=x+.003,
                    left_gaze_y=y,right_gaze_y=y,binocular_gaze_x=x,binocular_gaze_y=y,left_confidence=q,right_confidence=q,
                    left_eye_quality=q,right_eye_quality=q,overall_quality=q,valid=valid,binocular_valid=valid,left_eye_valid=valid,right_eye_valid=valid,
                    left_eye_openness='OPEN' if valid else 'CLOSED',right_eye_openness='OPEN' if valid else 'CLOSED',
                    left_eye_pixel_width=62,right_eye_pixel_width=60,camera_fps=30,head_yaw_deg=2*math.sin(i/20),head_pitch_deg=1,head_roll_deg=0))
        rec.close()
window=MainWindow(root);window.setWindowTitle('Amble Product QA — synthetic data');window.show();window.navigate('Analytics')
app.exec()
