"""Import DamIT Runner's flood package (a separate plugin, declared in metadata plugin_dependencies): the 2D
screening engine, the breach hydrographs, the toe-band inflow and the raster I/O live there, once."""
import os
import sys


class RunnerMissing(ImportError):
    pass


def flood():
    try:
        from damit_runner import flood as F                    # installed plugin (plugins dir on sys.path)
        return F
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.isdir(os.path.join(here, "damit_runner")) and here not in sys.path:
            sys.path.append(here)                              # monorepo checkout / tests
            try:
                from damit_runner import flood as F
                return F
            except ImportError:
                pass
        raise RunnerMissing("DamIT Runner is not installed. Install the 'DamIT Runner' plugin (it holds the 2D "
                            "screening engine the Screener's engine2d step runs).")


def modules():
    """(breach, damfolder, model, rasters, screen) of damit_runner.flood."""
    flood()
    from damit_runner.flood import breach, damfolder, model, rasters, screen
    return breach, damfolder, model, rasters, screen


def tm11_charts():
    """DamIT Hazard's digitized TM-11 houses / mobile-homes charts, or None when DamIT Hazard is not installed
    (the preliminary class then has no M1 chart zones; DamIT Hazard classifies the finished run anyway)."""
    try:
        from damit_hazard.engine import tm11
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if not os.path.isdir(os.path.join(here, "damit_hazard")):
            return None
        if here not in sys.path:
            sys.path.append(here)
        try:
            from damit_hazard.engine import tm11
        except ImportError:
            return None
    try:
        with open(tm11.DEFAULT_FILE, encoding="utf-8") as fh:
            import json
            return tm11, tm11.Charts(json.load(fh))
    except (OSError, ValueError):
        return None
