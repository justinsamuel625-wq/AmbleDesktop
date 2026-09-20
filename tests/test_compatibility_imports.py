"""Old public import paths remain available during the package refactor."""


def test_core_compatibility_imports():
    from amble.core.domain import EyeSample as CanonicalEyeSample
    from amble.core.preferences import preference as canonical_preference
    from amble.core.session_control import ProtocolClock as CanonicalClock
    from amble.domain import EyeSample
    from amble.preferences import preference
    from amble.session_control import ProtocolClock

    assert EyeSample is CanonicalEyeSample
    assert preference is canonical_preference
    assert ProtocolClock is CanonicalClock


def test_analysis_and_ui_compatibility_imports():
    from amble.analysis.quality import QualityThresholds as CanonicalThresholds
    from amble.analysis.research import filter_rows as canonical_filter_rows
    from amble.quality import QualityThresholds
    from amble.research import filter_rows
    from amble.ui.explorer import RawDataPage
    from amble.ui.pages.raw_data import RawDataPage as CanonicalRawDataPage
    from amble.ui.pages.settings import SettingsPage as CanonicalSettingsPage
    from amble.ui.settings import SettingsPage
    from amble.ui.widgets import LivePlot
    from amble.ui.components import LivePlot as CanonicalLivePlot

    assert QualityThresholds is CanonicalThresholds
    assert filter_rows is canonical_filter_rows
    assert RawDataPage is CanonicalRawDataPage
    assert SettingsPage is CanonicalSettingsPage
    assert LivePlot is CanonicalLivePlot
