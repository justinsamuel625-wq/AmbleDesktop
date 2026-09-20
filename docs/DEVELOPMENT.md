# Amble Development Guide

## Repository layout

```text
AmbleDesktop/
|-- .github/workflows/        # CI
|-- docs/                     # Architecture and measurement documentation
|-- scripts/                  # Manual validation utilities
|-- src/amble/
|   |-- core/                 # Domain, preferences, protocol clock
|   |-- experiments/          # Definitions and pure runtime
|   |-- analysis/             # Metrics, quality, research queries
|   |-- storage/              # Store, recorder, exports
|   |-- tracking/             # Interfaces, adapters, webcam helpers
|   |-- ui/
|   |   |-- main_window.py    # Assembly and coordination only
|   |   |-- pages/            # One module per screen
|   |   +-- components/       # Reusable focused widgets
|   +-- assets/               # Packaged runtime assets
+-- tests/                    # Automated regression tests
```

## Where new work belongs

- Add domain records, enums, validation, or cross-cutting settings under
  `core/`.
- Add experiment presets in `experiments/definitions.py`; add pure stimulus
  behavior in `experiments/runtime.py`.
- Add mathematical metrics in `analysis/metrics.py`, quality evidence/scoring
  in `analysis/quality.py`, and persisted-session comparisons in
  `analysis/research.py`.
- Add metadata/index operations in `storage/store.py`, acquisition artifact
  logic in `storage/recorder.py`, and outward copies/bundles in
  `storage/exports.py`.
- Add tracker implementations under `tracking/`. Keep camera discovery and
  dependency diagnostics in `tracking/camera.py`; keep landmark/image geometry
  helpers in `tracking/webcam_helpers.py`.
- Add a screen as one module under `ui/pages/`. Add a reusable visual primitive
  under `ui/components/`. Keep `ui/main_window.py` focused on assembly,
  navigation, signal wiring, and active-session coordination.

Compatibility modules at the former import paths are intentionally tiny. Do
not put new behavior into them, and do not duplicate implementations there.

## Development checks

Install and run the full automated suite:

```powershell
python -m pip install -e ".[dev]"
$env:QT_QPA_PLATFORM = "offscreen"
$env:QTWEBENGINE_CHROMIUM_FLAGS = "--disable-gpu"
python -m compileall -q src tests scripts
python -m pytest
```

Safe simulator validation:

```powershell
python scripts/experiment_workflow_check.py
```

The hardware scripts under `scripts/` are supplemental. Run them only when a
camera is available, and document unavailable or exclusively locked hardware
instead of treating it as an automated-test failure.

GitHub Actions performs editable installation, compilation, and the complete
test suite for every push and pull request.
