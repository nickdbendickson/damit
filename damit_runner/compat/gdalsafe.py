"""GDAL calls that behave the same whether GDAL's Python exceptions are switched on or off.

`gdal.UseExceptions()` is process-wide in the GDAL bindings QGIS ships: a plugin that calls it
at import time changes GDAL for QGIS and every other plugin (code written for the default mode
checks `if ds is None` and then meets an exception instead). The three suite plugins therefore
never change the mode (damsuite 1.3.0); they call GDAL through these helpers, which raise
RuntimeError - the exception type GDAL's exception mode raises - with GDAL's own message when
GDAL returns nothing, so `except RuntimeError` handlers work in both modes.

osgeo is imported only when a helper is called (damsuite itself stays importable without GDAL).
"""


def last_error(gdal=None):
    """GDAL's last error message, '' when there is none (never raises)."""
    try:
        if gdal is None:
            from osgeo import gdal
        return (gdal.GetLastErrorMsg() or "").strip()
    except Exception:                                            # noqa
        return ""


def checked(result, what, gdal=None):
    """`result` of a GDAL call (Open, Warp, Translate, BuildVRT, Create, ...); RuntimeError
    "<what> failed: <GDAL message>" when it is None."""
    if result is None:
        msg = last_error(gdal)
        raise RuntimeError("{} failed{}".format(what, ": " + msg if msg else ""))
    return result


def open_raster(path, update=False):
    """gdal.Open(path) (read-only, or update), or RuntimeError naming the file."""
    from osgeo import gdal
    mode = gdal.GA_Update if update else gdal.GA_ReadOnly
    try:
        ds = gdal.Open(path, mode)
    except RuntimeError as e:                    # exception mode: add the file name
        raise RuntimeError("GDAL cannot open {}: {}".format(path, e)) from None
    return checked(ds, "GDAL cannot open {} - opening".format(path), gdal)


def open_vector(path, update=False):
    """ogr.Open(path), or RuntimeError naming the file."""
    from osgeo import ogr
    try:
        ds = ogr.Open(path, 1 if update else 0)
    except RuntimeError as e:
        raise RuntimeError("OGR cannot open {}: {}".format(path, e)) from None
    if ds is None:
        raise RuntimeError("OGR cannot open {}{}".format(path, ": " + last_error() if last_error() else ""))
    return ds


def _uses_exceptions(module):
    try:
        return bool(module.GetUseExceptions())
    except Exception:                                            # noqa - an old binding without the getter
        return False


class gdal_exceptions(object):
    """GDAL Python exceptions on for one block (or, as a decorator, one call) only. DamIT addition (audit L-1,
    2026-11-20), the same idea as DamSafety PMP's core/gdalsafe.gdal_exceptions() and the Atlas 14 core's
    gdal_raising(): each osgeo module named ("gdal", "ogr", "osr"; default all three) that is off is switched on
    on entry and off again on exit, in reverse order (GDAL >= 3.7 keeps the error handlers on a stack), so the
    process-wide mode QGIS and the other plugins see never changes. Code inside behaves as it did under a
    process-wide gdal.UseExceptions(): a failed call raises RuntimeError."""

    def __init__(self, *names):
        self.names = names or ("gdal", "ogr", "osr")
        self._switched = []

    def __enter__(self):
        import importlib
        switched = []
        try:
            for name in self.names:
                module = importlib.import_module("osgeo." + name)
                if not _uses_exceptions(module):
                    module.UseExceptions()
                    switched.append(module)
        except BaseException:
            _restore(switched)
            raise
        self._switched.append(switched)
        return self

    def __exit__(self, *exc):
        _restore(self._switched.pop())
        return False

    def __call__(self, func):
        import functools

        @functools.wraps(func)
        def wrapper(*a, **k):
            with gdal_exceptions(*self.names):
                return func(*a, **k)
        return wrapper


def _restore(switched):
    for module in reversed(switched):
        try:
            module.DontUseExceptions()
        except Exception:                                        # noqa - never fails a run
            pass
