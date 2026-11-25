"""damit_runner.damsuite.gdalsafe IS damit_runner.compat.gdalsafe (same module object), for the
vendored Boann's `from ...damsuite import gdalsafe` (see __init__.py)."""
import sys

from ..compat import gdalsafe as _gdalsafe

sys.modules[__name__] = _gdalsafe
