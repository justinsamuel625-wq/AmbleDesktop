"""Compatibility alias for ``amble.ui.explorer``."""

import sys

from amble.ui.pages import raw_data as _implementation

sys.modules[__name__] = _implementation
