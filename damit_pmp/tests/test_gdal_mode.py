"""audit 2026-11-20: DamIT PMP and DamIT Hazard Lite never change GDAL's process-wide exception mode.

gdal / ogr.UseExceptions() is process-wide in the GDAL bindings QGIS ships. damit_pmp.gridstats and
damit_hazardlite.sampling called it at import, and gisgrid, temporal, watershed, demfetch, anugarain and
ws_algs inside functions, never switching back, so loading or using either plugin changed GDAL for QGIS and
every other plugin. Each check runs in a fresh Python, in both starting modes, and asserts the mode
(gdal.GetUseExceptions() / ogr.GetUseExceptions()) is the same after importing the module and after calling
its GDAL code, on success and on failure. Needs GDAL (skipped without it); no QGIS (Hazard Lite's qgis.core
imports are stubbed).
"""
import os
import re
import subprocess
import sys
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from osgeo import gdal, ogr  # noqa: F401
    HAVE_GDAL = True
except ImportError:                                      # pragma: no cover - no GDAL here
    HAVE_GDAL = False

PRELUDE = textwrap.dedent("""
    import os, sys, tempfile, types, warnings
    warnings.simplefilter("ignore")
    sys.path.insert(0, {root!r})
    from osgeo import gdal, ogr
    START = {start}
    for m in (gdal, ogr):
        m.UseExceptions() if START else m.DontUseExceptions()
    def mode():
        return (bool(gdal.GetUseExceptions()), bool(ogr.GetUseExceptions()))
    def same(where):
        if mode() != (START, START):
            print("MODE CHANGED", where, mode())
            sys.exit(3)
    TMP = tempfile.mkdtemp()
    def tif(path, w=4, h=4, val=1.0):
        import numpy as np
        from osgeo import osr
        ds = gdal.GetDriverByName("GTiff").Create(path, w, h, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((-97.0, 0.01, 0.0, 47.0, 0.0, -0.01))
        s = osr.SpatialReference(); s.ImportFromEPSG(4326)
        ds.SetProjection(s.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(np.full((h, w), val, dtype="float32"))
        ds = None
        return path
    def fails(fn, *a, **k):
        try:
            fn(*a, **k)
        except Exception:
            return True
        return False
""")

# module to import, then the calls that use GDAL (success and failure), all inside the child Python
CASES = {
    "gridstats": """
        from damit_pmp import gridstats as GS
        same("import")
        p = tif(os.path.join(TMP, "mw100yr24ha.tif"))
        wgs = gdal.Open(p).GetProjection()
        same("test raster")
        assert GS.point_value(p, -96.985, 46.985, wgs, 1.0) == 1.0
        st = GS.basin_stats(p, "POLYGON((-96.999 46.961,-96.961 46.961,-96.961 46.999,-96.999 46.999,-96.999 46.961))", wgs, 1.0)
        assert st["cells"] > 0, st
        same("calls")
        assert fails(GS.point_value, os.path.join(TMP, "missing.tif"), 0, 0, wgs)
        same("failed call")
    """,
    "gisgrid": """
        import numpy as np
        from damit_pmp import gisgrid as G
        same("import")
        G.write_geotiff(os.path.join(TMP, "out.tif"), np.ones((3, 3), dtype="float32"), (-97, 0.01, 0, 47, 0, -0.01))
        same("write_geotiff")
        assert fails(G.write_geotiff, os.path.join(TMP, "no", "such", "\\0bad.tif"), np.ones((2, 2), "float32"), (0, 1, 0, 0, 0, -1))
        same("failed write_geotiff")
    """,
    "temporal": """
        from osgeo import osr
        from damit_pmp import temporal as T
        same("import")
        d = os.path.join(TMP, "shp")
        s = osr.SpatialReference(); s.ImportFromEPSG(4269)
        ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(d)
        lyr = ds.CreateLayer("areas", s, ogr.wkbPolygon)
        lyr.CreateField(ogr.FieldDefn("Region", ogr.OFTInteger))
        f = ogr.Feature(lyr.GetLayerDefn()); f.SetField("Region", 2)
        f.SetGeometry(ogr.CreateGeometryFromWkt("POLYGON((-98 46,-96 46,-96 48,-98 48,-98 46))"))
        lyr.CreateFeature(f); f = lyr = ds = None
        same("test shapefile")
        assert T.locate_area(-97.0, 47.0, os.path.join(d, "areas.shp")) == 2
        same("locate_area")
        assert fails(T.locate_area, -97.0, 47.0, os.path.join(TMP, "missing.shp"))
        same("failed locate_area")
    """,
    "watershed": """
        import numpy as np
        from damit_pmp import watershed as W
        from damit_pmp.runner_shared.grid import Grid
        same("import")
        mask = np.zeros((5, 5), dtype=bool); mask[1:4, 1:4] = True
        g = Grid(np.zeros((5, 5)), 500000.0, 5200000.0, 10.0)
        assert "POLYGON" in W.mask_to_polygon_wkt(mask, g).upper()
        same("mask_to_polygon_wkt")
    """,
    "anugarain": """
        from damit_pmp import anugarain as AR
        from damit_pmp import lisfloodrain as LR
        same("import")
        assert fails(AR.read_model_grid, os.path.join(TMP, "missing.tif"), (0, 0, 10, 10), 1.0)
        same("failed read_model_grid")
        assert fails(AR.read_factor_on_grid, os.path.join(TMP, "missing.tif"), None)
        same("failed read_factor_on_grid")
    """,
    "demfetch": """
        from damit_pmp import demfetch as D
        same("import")
        assert fails(D.fetch, 0.0, 0.0, 1e7, 1.0, TMP)          # refused before any download: too many cells
        same("refused fetch")
    """,
    "hazardlite_sampling": """
        q = types.ModuleType("qgis"); qc = types.ModuleType("qgis.core")
        class _Any(object):
            def __init__(self, *a, **k):
                self.a = a
        for n in ("QgsCoordinateTransform", "QgsGeometry", "QgsPointXY", "QgsProject", "QgsRectangle",
                  "QgsUnitTypes", "QgsWkbTypes"):
            setattr(qc, n, _Any)
        q.core = qc; sys.modules["qgis"] = q; sys.modules["qgis.core"] = qc
        from damit_hazardlite import sampling as S
        same("import")
        r = S.Raster(tif(os.path.join(TMP, "depth.tif"), val=2.0))
        assert float(r.read((0, 0, 2, 2)).sum()) == 8.0
        same("read")
        try:
            S.Raster(os.path.join(TMP, "missing.tif"))
            raise AssertionError("no SamplingError")
        except S.SamplingError as e:
            assert "missing.tif" in str(e), e
        same("failed open")
    """,
}


@unittest.skipUnless(HAVE_GDAL, "GDAL (osgeo) is not installed")
class GdalModeUnchanged(unittest.TestCase):
    def _run(self, name, start):
        code = PRELUDE.format(root=ROOT, start=start) + textwrap.dedent(CASES[name]) + "\nprint('OK')\n"
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, "{} (start={}):\n{}\n{}".format(name, start, p.stdout[-2000:],
                                                                         p.stderr[-4000:]))
        self.assertIn("OK", p.stdout)

    def test_each_module_in_both_modes(self):
        for name in sorted(CASES):
            for start in (False, True):
                with self.subTest(module=name, start=start):
                    self._run(name, start)

    def test_no_plugin_level_switch_left(self):
        """No UseExceptions() call is left in the plugin code; atlas14.gdal_raising() is the one place that
        switches, and it switches back."""
        bad = []
        for folder in ("damit_pmp", "damit_hazardlite"):
            for base, dirs, files in os.walk(os.path.join(ROOT, folder)):
                dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "runner_shared", "templates")]
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    path = os.path.join(base, f)
                    with open(path, encoding="utf-8") as fh:
                        for i, ln in enumerate(fh, 1):
                            code = ln.split("#")[0]
                            if re.search(r"\b(gdal|ogr|osr)\.UseExceptions\(\)", code):
                                bad.append("{}:{}".format(os.path.relpath(path, ROOT), i))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
