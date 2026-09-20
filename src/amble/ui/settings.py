"""Compatibility alias for ``amble.ui.settings``."""

import sys

from amble.ui.pages import settings as _implementation

sys.modules[__name__] = _implementation
