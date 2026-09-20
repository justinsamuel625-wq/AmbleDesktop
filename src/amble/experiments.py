from __future__ import annotations

import math
from dataclasses import dataclass

from amble.domain import ExperimentConfig, ExperimentKind, PursuitTrajectory


@dataclass(slots=True)
class StimulusState:
    x: float
    y: float
    phase: str
    event: str = ""
    finished: bool = False


class ExperimentRuntime:
    """Pure timestamp-driven experiment state, independent of UI and tracker."""

    def __init__(self, config: ExperimentConfig) -> None:
        self.config = config
        self.duration_s = max(0.1, config.duration_s)

    def state_at(self, elapsed_s: float, phase: str) -> StimulusState:
        finished = elapsed_s >= self.duration_s
        t = min(max(elapsed_s, 0.0), self.duration_s)
        kind = self.config.kind
        if kind == ExperimentKind.FIXATION:
            x, y = self.config.fixation_target_x, self.config.fixation_target_y
        elif kind == ExperimentKind.PURSUIT:
            a = self.config.amplitude
            angle = 2 * math.pi * self.config.speed_hz * t
            trajectory = self.config.trajectory
            if trajectory == PursuitTrajectory.VERTICAL:
                x, y = 0.5, 0.5 + a * math.sin(angle)
            elif trajectory == PursuitTrajectory.CIRCULAR:
                x, y = 0.5 + a * math.cos(angle), 0.5 + a * math.sin(angle)
            elif trajectory == PursuitTrajectory.SINUSOIDAL:
                x = 0.5 + a * math.sin(angle)
                y = 0.5 + a * 0.45 * math.sin(2 * angle)
            else:
                x, y = 0.5 + a * math.sin(angle), 0.5
        elif kind == ExperimentKind.VERGENCE_PROXY:
            # Screen-only disparity cue; this is not physical depth or a true angle.
            x, y = 0.5 + self.config.amplitude * math.sin(2 * math.pi * self.config.speed_hz * t), 0.5
        else:
            x, y = 0.5, 0.5
        return StimulusState(x=x, y=y, phase=phase, finished=finished)


DEFAULT_EXPERIMENTS = {
    ExperimentKind.FIXATION: ExperimentConfig("Fixation Stability", ExperimentKind.FIXATION, duration_s=10),
    ExperimentKind.PURSUIT: ExperimentConfig("Smooth Pursuit", ExperimentKind.PURSUIT, duration_s=20),
    ExperimentKind.VERGENCE_PROXY: ExperimentConfig("Screen Vergence Proxy", ExperimentKind.VERGENCE_PROXY, duration_s=20, speed_hz=.15, amplitude=.12),
    ExperimentKind.EXTERNAL_NEAR_FAR: ExperimentConfig("External Near–Far", ExperimentKind.EXTERNAL_NEAR_FAR, duration_s=30),
}
