import json

import pytest
from PySide6.QtCore import Qt

from amble.core.domain import ExperimentConfig, ExperimentKind, PursuitTrajectory
from amble.experiments.runtime import ExperimentRuntime
from amble.ui.main_window import MainWindow, NewExperimentPage


def select_kind(page, kind):
    index = page.kind.findData(kind.value)
    assert index >= 0
    page.kind.setCurrentIndex(index)


def test_combo_string_is_explicitly_parsed_to_typed_enum(qtbot):
    page = NewExperimentPage(); qtbot.addWidget(page)
    assert isinstance(page.kind.currentData(), str)
    config = page.build_config()
    assert isinstance(config.kind, ExperimentKind)
    assert isinstance(config.trajectory, PursuitTrajectory)
    assert config.to_dict()["kind"] == "fixation"


@pytest.mark.parametrize(("kind", "trajectory", "speed", "amplitude", "target"), [
    (ExperimentKind.FIXATION, False, False, False, True),
    (ExperimentKind.PURSUIT, True, True, True, False),
    (ExperimentKind.VERGENCE_PROXY, False, True, True, False),
    (ExperimentKind.EXTERNAL_NEAR_FAR, False, False, False, False),
])
def test_experiment_specific_field_visibility(qtbot, kind, trajectory, speed, amplitude, target):
    page = NewExperimentPage(); qtbot.addWidget(page); page.show()
    select_kind(page, kind)
    assert page.trajectory.isVisible() is trajectory
    assert page.speed.isVisible() is speed
    assert page.amplitude.isVisible() is amplitude
    assert page.target_x.isVisible() is target
    assert page.target_y.isVisible() is target
    assert page.target_size.isVisible() is target


def test_numeric_controls_bounds_keyboard_and_values_reach_runtime(qtbot):
    page = NewExperimentPage(); qtbot.addWidget(page); page.show(); select_kind(page, ExperimentKind.PURSUIT)
    page.duration.setValue(page.duration.minimum()); page.duration.setFocus(); qtbot.keyClick(page.duration, Qt.Key_Down)
    assert page.duration.value() == page.duration.minimum()
    page.duration.setValue(17); page.speed.setValue(.35); page.amplitude.setValue(.22)
    page.trajectory.setCurrentIndex(page.trajectory.findData(PursuitTrajectory.VERTICAL.value))
    config = page.build_config(); runtime = ExperimentRuntime(config)
    assert config.duration_s == 17
    assert config.speed_hz == pytest.approx(.35)
    assert config.amplitude == pytest.approx(.22)
    assert config.trajectory == PursuitTrajectory.VERTICAL
    assert runtime.state_at(1.0, "pre").x == pytest.approx(.5)


@pytest.mark.parametrize("kind", [ExperimentKind.FIXATION, ExperimentKind.PURSUIT, ExperimentKind.VERGENCE_PROXY])
def test_each_implemented_experiment_starts_with_simulator(qtbot, tmp_path, kind):
    window = MainWindow(tmp_path / kind.value); qtbot.addWidget(window)
    page = window.pages["New Experiment"]; select_kind(page, kind)
    config = page.build_config()
    window.start_session("P-REGRESSION", config, False)
    assert window.recorder is not None
    assert window.config.kind is kind
    assert isinstance(window.runtime, ExperimentRuntime)
    metadata = json.loads((window.recorder.session_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["experiment"]["kind"] == kind.value
    assert metadata["preferred_eye_width_min_px"] == window.pages["Hardware"].eye_width_min.value()
    assert metadata["preferred_eye_width_max_px"] == window.pages["Hardware"].eye_width_max.value()
    assert metadata["quality_threshold"] == window.pages["Hardware"].quality_threshold.value() / 100
    assert metadata["tracker_backend"] == "simulated"
    assert metadata["camera_resolution"] == [1280, 720]
    window.recorder.close(); window.recorder = None; window.close()


def test_fixation_settings_control_runtime_target_and_size(qtbot):
    page = NewExperimentPage(); qtbot.addWidget(page); select_kind(page, ExperimentKind.FIXATION)
    page.target_x.setValue(.25); page.target_y.setValue(.75); page.target_size.setValue(12)
    config = page.build_config(); state = ExperimentRuntime(config).state_at(1, "pre")
    assert (state.x, state.y) == pytest.approx((.25, .75))
    assert config.target_size_px == 12


def test_convergence_config_validation_is_intentional():
    config = ExperimentConfig("Screen Vergence Proxy", "vergence_proxy", duration_s=5, speed_hz=.2, amplitude=.12)
    assert config.kind is ExperimentKind.VERGENCE_PROXY
    runtime = ExperimentRuntime(config)
    for elapsed in (0, 1, 2, 5):
        state = runtime.state_at(elapsed, "pre")
        assert 0 <= state.x <= 1 and state.y == .5
