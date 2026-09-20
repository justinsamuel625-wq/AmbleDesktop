"""Integration exercise for the three implemented on-screen experiment workflows."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from amble.core.domain import ExperimentKind, PursuitTrajectory
from amble.ui.main_window import MainWindow


def select(page, kind: ExperimentKind) -> None:
    page.kind.setCurrentIndex(page.kind.findData(kind.value))


def main() -> int:
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="amble_workflow_") as root:
        for kind in (ExperimentKind.FIXATION, ExperimentKind.PURSUIT, ExperimentKind.VERGENCE_PROXY):
            window = MainWindow(Path(root) / kind.value); window.show(); window.navigate("New Experiment")
            page = window.pages["New Experiment"]; select(page, kind); page.subject.setText(f"P-{kind.value.upper()}")
            page.duration.setValue(7); page.duration.stepUp(); page.duration.stepDown()
            if kind == ExperimentKind.FIXATION:
                page.target_x.setValue(.4); page.target_y.setValue(.6); page.target_size.setValue(9)
            elif kind == ExperimentKind.PURSUIT:
                page.trajectory.setCurrentIndex(page.trajectory.findData(PursuitTrajectory.CIRCULAR.value))
                page.speed.setValue(.35); page.amplitude.setValue(.2)
            else:
                page.speed.setValue(.15); page.amplitude.setValue(.12)
            expected = page.build_config(); page.start_button.click(); app.processEvents()
            print("SESSION_STARTED", kind.value, bool(window.recorder), window.config.kind.value if window.config else None)
            print("CONFIG", expected.to_dict())
            window.tick(); window.stop_session(); app.processEvents()
            print("SESSION_FINALIZED", kind.value, window.recorder is None)
            window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
