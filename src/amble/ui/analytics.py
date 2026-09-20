"""Compatibility alias for ``amble.ui.analytics``."""

import sys

from amble.ui.pages import analytics as _implementation

sys.modules[__name__] = _implementation
