# Amble Development Guide

This document defines where new code should live as Amble grows.

## Repository layout

```text
AmbleDesktop/
├── .github/
│   └── workflows/        # CI and repository automation
├── docs/                 # Architecture, metrics, quality, and developer docs
├── scripts/              # Manual validation and developer utility scripts
├── src/
│   └── amble/
│       ├── app.py        # Application entry point
│       ├── analysis.py   # Research analysis logic
│       ├── domain.py     # Core domain models
│       ├── experiments.py
│       ├── preferences.py
│       ├── quality.py
│       ├── research.py
│       ├── session_control.py
│       ├── storage.py
│       ├── assets/       # Packaged runtime assets
│       ├── tracking/     # Eye-tracker backends and interfaces
│       └── ui/           # PySide6 desktop UI
└── tests/                # Automated tests
```

## Placement rules

- Put application code under `src/amble/`, never at repository root.
- Put tracker integrations under `src/amble/tracking/`.
- Put Qt/PySide user-interface code under `src/amble/ui/`.
- Put reusable research calculations outside the UI layer.
- Put manual diagnostic or validation programs in `scripts/`.
- Put automated regression tests in `tests/`.
- Put architecture and measurement documentation in `docs/`.
- Do not commit generated research sessions, virtual environments, caches, build artifacts, or local hardware test data.

## Refactoring direction

The current package is intentionally being refactored incrementally rather than through a large one-time move.

Priority candidates:

1. `ui/main_window.py` — split page-specific UI and controllers as responsibilities become clearer.
2. `tracking/webcam.py` — separate camera acquisition, landmark processing, and frame/quality helpers if growth continues.
3. `storage.py` — separate persistence/indexing from session artifact/export concerns.
4. `analysis.py` and `quality.py` — keep research calculations independent from UI and hardware code.

Refactors should preserve existing public imports where practical and should include matching test updates.

## Before opening a pull request

Run:

```powershell
python -m pip install -e ".[dev]"
pytest
```

For UI-only smoke testing:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
pytest
```

Hardware scripts in `scripts/` are supplemental checks and should not replace automated tests.
