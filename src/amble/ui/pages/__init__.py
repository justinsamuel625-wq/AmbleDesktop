"""Application pages exposed to the main-window coordinator."""

from amble.ui.pages.analytics import AnalyticsPage
from amble.ui.pages.calibration import CalibrationPage
from amble.ui.pages.dashboard import DashboardPage
from amble.ui.pages.hardware import HardwarePage
from amble.ui.pages.live_session import LivePage
from amble.ui.pages.new_experiment import NewExperimentPage
from amble.ui.pages.raw_data import RawDataPage
from amble.ui.pages.settings import SettingsPage
from amble.ui.pages.subjects import SubjectsPage

__all__ = [
    "AnalyticsPage",
    "CalibrationPage",
    "DashboardPage",
    "HardwarePage",
    "LivePage",
    "NewExperimentPage",
    "RawDataPage",
    "SettingsPage",
    "SubjectsPage",
]
