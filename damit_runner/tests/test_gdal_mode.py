"""audit L-1 (2026-11-20): the DamIT Runner flood package never changes GDAL's process-wide exception mode.

flood/rasters._gdal() called gdal.UseExceptions() on every call and never switched back, so the first DamIT
flood read (dem_info, read_window, write_tif, ...) put QGIS and every other plugin into exception mode. The
functions now run under compat.gdalsafe.gdal_exceptions(), which switches exceptions on for that call only.

Each check runs in a fresh Python, in both starting modes, and asserts gdal / ogr / osr.GetUseExceptions() is
the same after the import, after the GDAL calls and after a failed call; inside the calls a GDAL failure still
raises (RuntimeError), as before. Also a static check that no gdal/ogr/osr.UseExceptions() call is left in
damit_runner's plugin code (tests excluded). Needs GDAL (skipped without it) and numpy; no QGIS.
"""
import os
import subprocess
import sys
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from osgeo import gdal, ogr, osr  # noqa: F401
    HAVE_GDAL = True
except ImportError:                                      # pragma: no cover - no GDAL here
    HAVE_GDAL = False

PRELUDE = textwrap.dedent("""
    import os, sys, tempfile, warnings
    warnings.simplefilter("ignore")
    sys.path.insert(0, {root!r})
    from osgeo import gdal, ogr, osr
    START = {start}
    for m in (gdal, ogr, osr):
        m.UseExceptions() if START else m.DontUseExceptions()
    def mode():
        return (bool(gdal.GetUseExceptions()), bool(ogr.GetUseExceptions()), bool(osr.GetUseExceptions()))
    def same(where):
        if mode() != (START, START, START):
            print("MODE CHANGED", where, mode())
            sys.exit(3)
    TMP = tempfile.mkdtemp()
    def tif(path, w=6, h=5, val=300.0):
        import numpy as np
        ds = gdal.GetDriverByName("GTiff").Create(path, w, h, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((500000.0, 10.0, 0.0, 5200000.0, 0.0, -10.0))
        s = osr.SpatialReference(); s.ImportFromEPSG(26914)
        ds.SetProjection(s.ExportToWkt())
        b = ds.GetRasterBand(1)
        b.WriteArray(np.full((h, w), val, dtype="float32"))
        b.SetUnitType("m")
        ds = None
        return path
    def raises(exc, fn, *a, **k):
        try:
            fn(*a, **k)
        except exc:
            return True
        except Exception as e:
            print("WRONG EXCEPTION", type(e).__name__, e)
            sys.exit(4)
        return False
""")

CASES = {
    "rasters": """
        import numpy as np
        from damit_runner.flood import rasters as R
        same("import")
        p = tif(os.path.join(TMP, "dem.tif"))
        same("test raster")
        info = R.dem_info(p)
        assert info["metric"] and info["size"] == (6, 5), info
        wkt = info["wkt"]
        g = R.read_window(p, (500000.0, 5199950.0, 500060.0, 5200000.0), 10.0, wkt)
        assert np.nanmax(g.data) == 300.0, g.data
        pts = R.transform_points([(500000.0, 5200000.0)], wkt, "EPSG:4326")
        assert -100 < pts[0][0] < -95, pts
        out = R.write_tif(os.path.join(TMP, "out", "depth.tif"), g, wkt)
        g2, wkt2 = R.read_tif(out)
        assert g2.data.shape == g.data.shape and wkt2
        cls = np.zeros(g.data.shape, dtype=int); cls[1:3, 1:3] = 1
        R.polygonize(os.path.join(TMP, "flood.geojson"), cls, g, wkt, labels={1: "wet"})
        assert R.srs_from("EPSG:4326").IsGeographic()
        same("calls")
        # failures still raise inside the call (exceptions are on for the call), and leave the mode alone
        assert raises(RuntimeError, R.dem_info, os.path.join(TMP, "missing.tif"))
        same("failed dem_info")
        assert raises(RuntimeError, R.read_tif, os.path.join(TMP, "missing.tif"))
        same("failed read_tif")
        assert raises(RuntimeError, R.srs_from, "EPSG:999999999")
        same("failed srs_from")
    """,
    "terrain3dep_and_pack_terrain": """
        from damit_runner.flood import terrain3dep as T3
        from damit_screener.core import pack_terrain as PT
        same("import")
        p = tif(os.path.join(TMP, "dem.tif"))
        b = PT.raster_bounds(p)
        assert b and b[4] == 26914, b
        assert PT.raster_bounds(os.path.join(TMP, "missing.tif")) is None
        open(os.path.join(TMP, "junk.tif"), "w").write("not a raster")
        assert PT.raster_bounds(os.path.join(TMP, "junk.tif")) is None
        same("pack_terrain.raster_bounds")
    """,
    "gdalsafe_nesting": """
        from damit_runner.compat.gdalsafe import gdal_exceptions
        same("import")
        with gdal_exceptions():
            assert mode() == (True, True, True)
            with gdal_exceptions("gdal"):
                assert gdal.GetUseExceptions()
            assert mode() == (True, True, True)
        same("nested block")
        @gdal_exceptions("gdal")
        def boom():
            assert gdal.GetUseExceptions()
            raise ValueError("x")
        assert raises(ValueError, boom)
        same("decorated call that raised")
    """,
}


@unittest.skipUnless(HAVE_GDAL, "needs GDAL")
class GdalModeUnchanged(unittest.TestCase):
    def run_case(self, name, start):
        code = PRELUDE.format(root=ROOT, start=start) + textwrap.dedent(CASES[name]) + "\nprint('OK')\n"
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, "{} (start {}): {}\n{}".format(name, start, r.stdout, r.stderr[-3000:]))
        self.assertIn("OK", r.stdout)

    def test_all_cases_both_modes(self):
        for name in sorted(CASES):
            for start in (False, True):
                with self.subTest(case=name, start=start):
                    self.run_case(name, start)


class NoProcessWideSwitch(unittest.TestCase):
    """Static: no gdal/ogr/osr.UseExceptions() call in damit_runner's or damit_screener's plugin code (tests
    excluded); compat/gdalsafe.py is the one place that switches, and only inside gdal_exceptions()."""

    def test_no_use_exceptions_in_runner_or_screener(self):
        import ast
        hits = []
        for pkg in ("damit_runner", "damit_screener"):
            for base, dirs, files in os.walk(os.path.join(ROOT, pkg)):
                dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
                for f in files:
                    path = os.path.join(base, f)
                    if not f.endswith(".py") or path.endswith(os.path.join("compat", "gdalsafe.py")):
                        continue
                    with open(path, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read(), path)
                    for node in ast.walk(tree):
                        fn = getattr(node, "func", None)
                        if (isinstance(node, ast.Call) and isinstance(fn, ast.Attribute)
                                and fn.attr == "UseExceptions" and isinstance(fn.value, ast.Name)
                                and fn.value.id in ("gdal", "ogr", "osr")):
                            hits.append("{}:{}".format(os.path.relpath(path, ROOT), node.lineno))
        self.assertEqual(hits, [], "process-wide UseExceptions() calls: {}".format(hits))


if __name__ == "__main__":
    unittest.main()
