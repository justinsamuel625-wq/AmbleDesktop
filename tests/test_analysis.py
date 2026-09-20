import math

import numpy as np
import pandas as pd

from amble.analysis import analyze_session, bcea, drift_rate, pursuit_gain, pursuit_lag_ms


def sample_frame(n=120, noise=0.01):
    rng = np.random.default_rng(3)
    target_x = 0.5 + 0.25 * np.sin(np.linspace(0, 4 * np.pi, n))
    target_y = np.full(n, 0.5)
    gaze_x = target_x + rng.normal(0, noise, n)
    gaze_y = target_y + rng.normal(0, noise, n)
    return pd.DataFrame({
        "timestamp_ns": 1_700_000_000_000_000_000 + np.arange(n) * 16_666_667,
        "experiment_phase": ["pre"] * n,
        "target_x": target_x, "target_y": target_y,
        "left_gaze_x": gaze_x - 0.004, "left_gaze_y": gaze_y,
        "right_gaze_x": gaze_x + 0.004, "right_gaze_y": gaze_y,
        "binocular_gaze_x": gaze_x, "binocular_gaze_y": gaze_y,
        "left_confidence": np.full(n, .95), "right_confidence": np.full(n, .94),
        "valid": np.ones(n, dtype=bool),
    })


def test_bcea_is_positive_and_finite():
    frame = sample_frame()
    value = bcea(frame.binocular_gaze_x, frame.binocular_gaze_y)
    assert value > 0
    assert math.isfinite(value)


def test_pursuit_gain_and_lag_for_identical_signal():
    frame = sample_frame(noise=0)
    assert pursuit_gain(frame.target_x, frame.binocular_gaze_x) == 1.0
    assert pursuit_lag_ms(frame.timestamp_ns, frame.target_x, frame.binocular_gaze_x) == 0.0


def test_quality_gate_suppresses_interpretation():
    frame = sample_frame()
    frame.loc[:100, "valid"] = False
    metrics = analyze_session(frame, "fixation", .6)
    mean_error = next(row for row in metrics if row["name"] == "mean_gaze_error")
    assert mean_error["value"] is None
    assert mean_error["quality_ok"] is False
    assert mean_error["details"]["reason"] == "Insufficient tracking quality"


def test_session_analysis_has_traceable_phase_metrics():
    metrics = analyze_session(sample_frame(), "smooth_pursuit", .6)
    names = {item["name"] for item in metrics}
    assert {"mean_gaze_error", "bcea_68", "pursuit_rmse", "pursuit_gain", "pursuit_lag", "vergence_proxy_mean"} <= names
    assert all(item["phase"] == "pre" for item in metrics)


def test_drift_rate_uses_elapsed_time():
    x = np.r_[np.zeros(50), np.ones(50)]
    y = np.zeros(100)
    assert drift_rate(x, y, 2.0) == .5

