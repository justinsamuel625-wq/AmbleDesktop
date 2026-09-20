"""Built-in experiment definitions."""

from amble.core.domain import ExperimentConfig, ExperimentKind


DEFAULT_EXPERIMENTS = {
    ExperimentKind.FIXATION: ExperimentConfig(
        "Fixation Stability", ExperimentKind.FIXATION, duration_s=10
    ),
    ExperimentKind.PURSUIT: ExperimentConfig(
        "Smooth Pursuit", ExperimentKind.PURSUIT, duration_s=20
    ),
    ExperimentKind.VERGENCE_PROXY: ExperimentConfig(
        "Screen Vergence Proxy",
        ExperimentKind.VERGENCE_PROXY,
        duration_s=20,
        speed_hz=0.15,
        amplitude=0.12,
    ),
    ExperimentKind.EXTERNAL_NEAR_FAR: ExperimentConfig(
        "External Near–Far", ExperimentKind.EXTERNAL_NEAR_FAR, duration_s=30
    ),
}

__all__ = ["DEFAULT_EXPERIMENTS"]
