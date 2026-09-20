"""Compatibility alias for ``amble.ui.subjects``."""

import sys

from amble.ui.pages import subjects as _implementation

sys.modules[__name__] = _implementation
