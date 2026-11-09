"""Find DamIT Core (declared in plugin_dependencies): the installed plugin, else the folder beside
this one (a checkout of the damit repository, CI and tests)."""
import os
import sys


def ensure():
    try:
        import damit_core.lib  # noqa: F401
        return
    except ImportError:
        pass
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(here, "damit_core")) and here not in sys.path:
        sys.path.append(here)
    try:
        import damit_core.lib  # noqa: F401
    except ImportError:
        raise ImportError("DamIT Core is not installed. Install the 'DamIT Core' plugin (QGIS Plugin Manager).")


ensure()
