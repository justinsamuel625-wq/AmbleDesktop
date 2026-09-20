# Architecture

```text
EyeTracker / future SensorStream
          │ timestamped EyeSample
          ▼
ExperimentRuntime ── exact target + phase + event ──► SessionRecorder
                                                        │
                                      append-only CSV + events.csv
                                                        │ close
                                      Parquet + SQLite metadata
                                                        │
                              ┌─────────────────────────┴────────────────────┐
                              ▼                                              ▼
                     analysis.py                                      Raw Data page
                              │                                              │
                         metrics table                              same persisted rows
                              │
                        Analytics page
```

The acquisition, experiment, storage, analysis, and presentation layers communicate through explicit domain records. `EyeTracker` can be implemented by an OpenFace subprocess adapter, Pupil Labs, Tobii, a VR runtime, or another binocular tracker without changing storage or analysis. `SensorStream` reserves the equivalent boundary for EEG, IMU, heart rate, VR, and future LSL streams.

Two clocks are stored: UTC Unix nanoseconds permit cross-file alignment and a monotonic tracker timestamp supports interval calculations. A future LSL adapter should additionally store source clock, correction, and synchronized LSL time.

