from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from amble.core.domain import MetricKind

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    unit: str
    kind: MetricKind
    algorithm: str
    assumptions: str
    required_quality: str


METRIC_DEFINITIONS = {
    "calibration_error": MetricDefinition("calibration_error", "px", MetricKind.DIRECT,
        "Mean binocular target-to-gaze error across valid calibration points", "Calibration used the active tracker and display", "At least 7 valid points"),
    "valid_samples_pct": MetricDefinition("valid_samples_pct", "%", MetricKind.DIRECT,
        "100 × valid rows / all rows", "Tracker validity flag is meaningful", "At least one row"),
    "mean_tracking_confidence": MetricDefinition("mean_tracking_confidence", "%", MetricKind.DIRECT,
        "100 × mean(min(left confidence, right confidence))", "Tracker confidence is calibrated by its vendor", "At least one row"),
    "sampling_rate": MetricDefinition("sampling_rate", "Hz", MetricKind.DIRECT,
        "1 / median successive UTC timestamp interval", "Monotonic acquisition with at least two rows", "At least two rows"),
    "dropped_frames_pct": MetricDefinition("dropped_frames_pct", "%", MetricKind.ESTIMATED,
        "100 × missing frame identifiers / expected identifier span", "Frame identifiers increase by one per source frame", "At least two rows"),
    "mean_gaze_error": MetricDefinition("mean_gaze_error", "normalized screen units", MetricKind.ESTIMATED,
        "Mean Euclidean distance between binocular gaze and target", "Calibrated normalized coordinates", ">=60% valid samples"),
    "rms_gaze_error": MetricDefinition("rms_gaze_error", "normalized screen units", MetricKind.ESTIMATED,
        "sqrt(mean(dx² + dy²))", "Stationary or known target", ">=60% valid samples"),
    "bcea_68": MetricDefinition("bcea_68", "normalized screen area", MetricKind.ESTIMATED,
        "2πkσxσy√(1-ρ²), k=-ln(1-0.68)", "Approximately bivariate gaze distribution", ">=30 valid samples"),
    "fixation_drift": MetricDefinition("fixation_drift", "normalized units/s", MetricKind.ESTIMATED,
        "Distance between first and last robust 10% gaze centroids divided by time", "Stable target", ">=30 valid samples"),
    "left_fixation_rms": MetricDefinition("left_fixation_rms", "normalized screen units", MetricKind.ESTIMATED,
        "Left-eye RMS target error", "Calibrated normalized coordinates", ">=60% valid samples"),
    "right_fixation_rms": MetricDefinition("right_fixation_rms", "normalized screen units", MetricKind.ESTIMATED,
        "Right-eye RMS target error", "Calibrated normalized coordinates", ">=60% valid samples"),
    "left_bcea_68": MetricDefinition("left_bcea_68", "normalized screen area", MetricKind.ESTIMATED,
        "Left-eye 68% bivariate contour ellipse area", "Approximately bivariate distribution", ">=30 valid samples"),
    "right_bcea_68": MetricDefinition("right_bcea_68", "normalized screen area", MetricKind.ESTIMATED,
        "Right-eye 68% bivariate contour ellipse area", "Approximately bivariate distribution", ">=30 valid samples"),
    "left_right_error_asymmetry": MetricDefinition("left_right_error_asymmetry", "normalized screen units", MetricKind.ESTIMATED,
        "Absolute difference between left- and right-eye RMS target error", "Comparable per-eye calibration", ">=60% valid samples"),
    "vergence_proxy_mean": MetricDefinition("vergence_proxy_mean", "normalized horizontal difference", MetricKind.PROXY,
        "Mean(right gaze x - left gaze x)", "Comparable calibrated eye coordinates; not a clinical vergence angle", ">=60% valid samples"),
    "pursuit_rmse": MetricDefinition("pursuit_rmse", "normalized screen units", MetricKind.ESTIMATED,
        "Root mean square target-to-binocular-gaze error", "Synchronized target timestamps", ">=60% valid samples"),
    "pursuit_lag": MetricDefinition("pursuit_lag", "ms", MetricKind.ESTIMATED,
        "Cross-correlation lag maximizing target/gaze correlation", "Near-uniform sampling and periodic target", ">=2 cycles preferred"),
    "pursuit_gain": MetricDefinition("pursuit_gain", "ratio", MetricKind.ESTIMATED,
        "Gaze standard deviation / target standard deviation after de-meaning", "Smooth target trajectory", ">=60% valid samples"),
}


def _clean(frame, columns: list[str], threshold: float) -> tuple[object, float, bool]:
    total = len(frame)
    if total == 0:
        return frame, 0.0, False
    valid_mask = frame["valid"].astype(str).str.lower().isin(["true", "1"]) if frame["valid"].dtype == object else frame["valid"].astype(bool)
    confidence = frame[["left_confidence", "right_confidence"]].min(axis=1) >= threshold
    clean = frame.loc[valid_mask & confidence].dropna(subset=columns)
    ratio = len(clean) / total
    return clean, ratio, ratio >= threshold


def analyze_session(frame, experiment_kind: str, quality_threshold: float = 0.60) -> list[dict]:
    """Compute explicit metrics only when their documented quality gate passes."""
    if pd is None:
        raise RuntimeError("Pandas is required for analysis")
    if frame.empty:
        return []
    output: list[dict] = []
    phases = sorted(str(p) for p in frame["experiment_phase"].fillna("all").unique())
    for phase in phases:
        subset = frame[frame["experiment_phase"].fillna("all").astype(str) == phase]
        raw_confidence = subset[["left_confidence", "right_confidence"]].min(axis=1).dropna()
        output.append(_metric(phase, "mean_tracking_confidence", float(raw_confidence.mean() * 100) if len(raw_confidence) else None, bool(len(raw_confidence))))
        if len(subset) >= 2:
            intervals = np.diff(np.sort(subset["timestamp_ns"].to_numpy(np.int64))) / 1e9
            positive = intervals[intervals > 0]
            rate = 1.0 / float(np.median(positive)) if len(positive) else None
            frame_numbers = subset["frame_number"].dropna().to_numpy(int) if "frame_number" in subset else np.array([], dtype=int)
            expected = int(frame_numbers.max() - frame_numbers.min() + 1) if len(frame_numbers) else 0
            dropped = max(0, expected - len(np.unique(frame_numbers)))
            output.append(_metric(phase, "sampling_rate", rate, rate is not None))
            output.append(_metric(phase, "dropped_frames_pct", 100 * dropped / expected if expected else None, expected > 0))
        gaze, valid_ratio, quality_ok = _clean(
            subset, ["target_x", "target_y", "binocular_gaze_x", "binocular_gaze_y"], quality_threshold
        )
        output.append(_metric(phase, "valid_samples_pct", valid_ratio * 100, quality_ok=True))
        if quality_ok and len(gaze) >= 2:
            dx = gaze["binocular_gaze_x"].to_numpy(float) - gaze["target_x"].to_numpy(float)
            dy = gaze["binocular_gaze_y"].to_numpy(float) - gaze["target_y"].to_numpy(float)
            error = np.hypot(dx, dy)
            output.extend([
                _metric(phase, "mean_gaze_error", float(np.mean(error)), True),
                _metric(phase, "rms_gaze_error", float(np.sqrt(np.mean(error ** 2))), True),
            ])
            per_eye_values = {}
            for eye in ("left", "right"):
                ex = gaze[f"{eye}_gaze_x"].to_numpy(float) - gaze["target_x"].to_numpy(float)
                ey = gaze[f"{eye}_gaze_y"].to_numpy(float) - gaze["target_y"].to_numpy(float)
                eye_rms = float(np.sqrt(np.mean(ex ** 2 + ey ** 2)))
                per_eye_values[eye] = eye_rms
                output.append(_metric(phase, f"{eye}_fixation_rms", eye_rms, True))
            if len(gaze) >= 30:
                output.append(_metric(phase, "bcea_68", bcea(gaze["binocular_gaze_x"], gaze["binocular_gaze_y"]), True))
                output.append(_metric(phase, "left_bcea_68", bcea(gaze["left_gaze_x"], gaze["left_gaze_y"]), True))
                output.append(_metric(phase, "right_bcea_68", bcea(gaze["right_gaze_x"], gaze["right_gaze_y"]), True))
                elapsed = (gaze["timestamp_ns"].iloc[-1] - gaze["timestamp_ns"].iloc[0]) / 1e9
                output.append(_metric(phase, "fixation_drift", drift_rate(gaze["binocular_gaze_x"], gaze["binocular_gaze_y"], elapsed), True))
            output.append(_metric(phase, "left_right_error_asymmetry", abs(per_eye_values["left"] - per_eye_values["right"]), True))
            if experiment_kind == "smooth_pursuit":
                output.append(_metric(phase, "pursuit_rmse", float(np.sqrt(np.mean(error ** 2))), True))
                axis = "x" if np.std(gaze["target_x"]) >= np.std(gaze["target_y"]) else "y"
                target = gaze[f"target_{axis}"].to_numpy(float)
                observed = gaze[f"binocular_gaze_{axis}"].to_numpy(float)
                output.append(_metric(phase, "pursuit_gain", pursuit_gain(target, observed), True))
                output.append(_metric(phase, "pursuit_lag", pursuit_lag_ms(gaze["timestamp_ns"], target, observed), True))
        else:
            for name in ["mean_gaze_error", "rms_gaze_error"]:
                output.append(_metric(phase, name, None, False, {"reason": "Insufficient tracking quality"}))
        binocular, ratio, bino_ok = _clean(
            subset, ["left_gaze_x", "right_gaze_x"], quality_threshold
        )
        if bino_ok:
            proxy = (binocular["right_gaze_x"] - binocular["left_gaze_x"]).mean()
            output.append(_metric(phase, "vergence_proxy_mean", float(proxy), True))
        else:
            output.append(_metric(phase, "vergence_proxy_mean", None, False, {"reason": "Insufficient tracking quality"}))
    # Stored comparison rows make the pre/post interpretation explicit and exportable.
    by_phase = {(item["phase"], item["name"]): item for item in output}
    common = sorted({name for phase, name in by_phase if phase == "pre"} & {name for phase, name in by_phase if phase == "post"})
    for name in common:
        before, after = by_phase[("pre", name)], by_phase[("post", name)]
        if before["quality_ok"] and after["quality_ok"] and before["value"] is not None and after["value"] is not None:
            delta = after["value"] - before["value"]
            percent = delta / abs(before["value"]) * 100 if abs(before["value"]) > 1e-12 else None
            output.append({"phase": "pre_vs_post", "name": f"{name}_absolute_change", "value": delta,
                           "unit": before["unit"], "kind": before["kind"], "quality_ok": True,
                           "details": {"baseline": before["value"], "post": after["value"]}})
            output.append({"phase": "pre_vs_post", "name": f"{name}_percentage_change", "value": percent,
                           "unit": "%", "kind": before["kind"], "quality_ok": percent is not None,
                           "details": {"baseline": before["value"], "post": after["value"]}})
    return output


def _metric(phase: str, name: str, value: float | None, quality_ok: bool, details: dict | None = None) -> dict:
    definition = METRIC_DEFINITIONS[name]
    return {"phase": phase, "name": name, "value": value, "unit": definition.unit,
            "kind": definition.kind.value, "quality_ok": quality_ok, "details": details or {}}


def bcea(x, y, probability: float = 0.68) -> float:
    x_arr, y_arr = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(x_arr) < 2:
        return float("nan")
    sx, sy = np.std(x_arr, ddof=1), np.std(y_arr, ddof=1)
    rho = float(np.corrcoef(x_arr, y_arr)[0, 1]) if sx > 0 and sy > 0 else 0.0
    rho = max(-1.0, min(1.0, rho))
    k = -math.log(1.0 - probability)
    return float(2 * math.pi * k * sx * sy * math.sqrt(max(0.0, 1 - rho * rho)))


def drift_rate(x, y, elapsed_s: float) -> float:
    if elapsed_s <= 0:
        return float("nan")
    x_arr, y_arr = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    window = max(1, len(x_arr) // 10)
    delta = math.hypot(float(np.median(x_arr[-window:]) - np.median(x_arr[:window])),
                       float(np.median(y_arr[-window:]) - np.median(y_arr[:window])))
    return delta / elapsed_s


def pursuit_gain(target, gaze) -> float:
    target_std = float(np.std(np.asarray(target, dtype=float)))
    return float(np.std(np.asarray(gaze, dtype=float)) / target_std) if target_std > 1e-12 else float("nan")


def pursuit_lag_ms(timestamps_ns, target, gaze) -> float:
    target_arr = np.asarray(target, dtype=float) - np.mean(target)
    gaze_arr = np.asarray(gaze, dtype=float) - np.mean(gaze)
    if len(target_arr) < 3 or np.std(target_arr) == 0 or np.std(gaze_arr) == 0:
        return float("nan")
    correlation = np.correlate(gaze_arr, target_arr, mode="full")
    lag_samples = int(np.argmax(correlation) - (len(target_arr) - 1))
    times = np.asarray(timestamps_ns, dtype=np.int64)
    sample_ms = float(np.median(np.diff(times)) / 1e6)
    return lag_samples * sample_ms
