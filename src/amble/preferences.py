"""Compatibility alias for the pre-refactor ``amble.preferences`` path."""

import sys

from amble.core import preferences as _implementation

# Preserve module-level monkeypatching used by integrations and tests.
sys.modules[__name__] = _implementation
