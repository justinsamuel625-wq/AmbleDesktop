"""Validated preferences backed only by the application's existing QSettings."""
from pathlib import Path
from PySide6.QtCore import QSettings

# key: (default, minimum/choices, maximum). Unsupported policies are not offered.
SPECS = {
    'general/theme': ('dark', ('dark', 'light', 'system'), None),
    'general/data_directory': (str(Path.home() / 'Amble Research Data'), None, None),
    'general/last_subject': ('', None, None),
    'general/auto_subject': (False, None, None),
    'data/export_format': ('CSV', ('CSV', 'Parquet'), None),
    'hardware/minimum_binocular_quality': (70, 20, 95),
    'hardware/minimum_eye_quality': (70, 20, 95),
    'hardware/preferred_eye_width_min_px': (40, 28, 100),
    'hardware/preferred_eye_width_max_px': (75, 35, 140),
    'hardware/camera_index': (0, 0, 16),
    'hardware/backend': ('simulated', ('simulated', 'webcam', 'openface'), None),
    'camera/resolution': ('Device default', ('Device default', '640x480', '1280x720', '1920x1080'), None),
    'camera/fps': (30, 5, 120),
    'experiments/fixation_duration': (10, 2, 3600),
    'experiments/pursuit_duration': (20, 2, 3600),
    'experiments/countdown': (0, 0, 30),
    'experiments/transition_delay': (0, 0, 30),
    'analytics/window_seconds': (10, 1, 120),
    'analytics/show_invalid': (True, None, None),
    'analytics/smoothing': (False, None, None),
    'analytics/smoothing_window': (5, 1, 101),
    'research/overlay': (True, None, None),
    'research/diagnostics': (True, None, None),
    'research/log_level': ('INFO', ('DEBUG', 'INFO', 'WARNING', 'ERROR'), None),
}

def preference(key, settings=None):
    default, lower, upper = SPECS[key]
    value = (settings or QSettings()).value(key, default)
    try:
        if isinstance(default, bool):
            if isinstance(value, bool): return value
            if str(value).lower() in ('true', '1'): return True
            if str(value).lower() in ('false', '0'): return False
            return default
        if isinstance(default, int):
            value = int(value)
            return value if lower <= value <= upper else default
        value = str(value)
        if isinstance(lower, tuple) and value not in lower: return default
        return value
    except (TypeError, ValueError):
        return default

def restore_defaults(settings=None):
    settings = settings or QSettings()
    for key, (default, _, _) in SPECS.items(): settings.setValue(key, default)
    for key in ('hardware/preview_mode', 'hardware/preview_splitter_sizes', 'hardware/preview_height'):
        settings.remove(key)
    settings.sync()
