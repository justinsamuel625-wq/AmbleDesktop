# Architecture

Amble is organized by responsibility. Dependencies flow inward through domain
records and explicit interfaces; storage, analysis, and UI code do not own
tracker algorithms.

```text
tracking/EyeTracker -- timestamped core/EyeSample --+
                                                   v
experiments/ExperimentRuntime -- target + phase --> storage/SessionRecorder
                                                   |
                                  append-only CSV + events.csv
                                                   | close
                                  Parquet + SQLite metadata
                                                   |
                     +-----------------------------+-------------------------+
                     v                                                       v
             analysis/metrics                                       ui/pages/raw_data
                     |                                                       |
             persisted metrics                                      exact persisted rows
                     |
             ui/pages/analytics
```

## Package responsibilities

- `core/` defines domain records, enums, validation, settings, and monotonic
  protocol timing. It must not depend on UI or hardware modules.
- `experiments/` contains immutable built-in definitions and the pure,
  timestamp-driven stimulus runtime.
- `analysis/` contains mathematical metrics, explainable measurement-quality
  scoring, and queries over persisted sessions.
- `storage/` owns the SQLite index, session artifact recording/finalization,
  and export operations.
- `tracking/` owns tracker contracts and adapters. `camera.py` handles device
  probing/runtime diagnostics; `webcam_helpers.py` handles landmarks, image
  evidence, and pose geometry; `webcam.py` retains the public tracker API.
- `ui/pages/` owns individual screens. `ui/components/` owns reusable visual
  widgets. `ui/main_window.py` assembles pages, connects signals, navigates,
  and coordinates the active session.

## Stable boundaries

`EyeTracker` can be implemented by OpenFace, Pupil Labs, Tobii, a VR runtime,
or another binocular tracker without changing storage or analysis.
`SensorStream` reserves the equivalent boundary for EEG, IMU, heart rate, VR,
and future LSL streams.

Two clocks are stored: UTC Unix nanoseconds permit cross-file alignment, and a
monotonic tracker timestamp supports interval calculations. A future LSL
adapter should also retain source clock, correction, and synchronized LSL time.

Compatibility modules preserve the former public paths (`amble.domain`,
`amble.quality`, `amble.research`, `amble.preferences`,
`amble.session_control`, and former `amble.ui` page/widget modules). They must
remain thin aliases; new implementations belong in the packages above.

