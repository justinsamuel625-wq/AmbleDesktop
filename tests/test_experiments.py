import pytest

from amble.domain import ExperimentConfig, ExperimentKind
from amble.experiments import ExperimentRuntime


@pytest.mark.parametrize("trajectory", ["horizontal", "vertical", "circular", "sinusoidal"])
def test_pursuit_targets_remain_on_screen(trajectory):
    config = ExperimentConfig("test", ExperimentKind.PURSUIT, duration_s=10, trajectory=trajectory, amplitude=.4)
    runtime = ExperimentRuntime(config)
    for step in range(101):
        state = runtime.state_at(step / 10, "pre")
        assert 0 <= state.x <= 1
        assert 0 <= state.y <= 1


def test_fixation_target_is_stationary():
    runtime = ExperimentRuntime(ExperimentConfig("fix", ExperimentKind.FIXATION))
    assert runtime.state_at(0, "pre").x == runtime.state_at(9, "pre").x == .5

