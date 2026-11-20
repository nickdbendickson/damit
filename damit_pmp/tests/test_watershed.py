"""damit_pmp:watershed pieces: the D8 delineation (watershed.py) and the 3DEP fetch (demfetch.py), on synthetic
terrain and a fake ImageServer. Needs numpy, scipy and GDAL (skips otherwise); no network, no QGIS."""
import os
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

try:
    import numpy as np
    import scipy  # noqa: F401
    from osgeo import gdal, ogr, osr
    gdal.UseExceptions()
    HAVE = True
except ImportError:                                            # pragma: no cover
    HAVE = False

if HAVE:
    from damit_pmp import demfetch
    from damit_pmp import watershed as W
    from damit_pmp.runner_shared.grid import NODATA, Grid


def valley(nx=44, ny=34, cell=30.0, tilt=0.005, side=0.03, frame=True):
    """A V-shaped valley draining west along its middle row; a one-cell NODATA frame (frame=True) so the basin does not
    touch the array edge. Returns (Grid, channel row)."""
    z = np.zeros((ny, nx))
    rc = ny // 2
    rows, cols = np.indices((ny, nx))
    z = 100.0 + side * cell * np.abs(rows - rc) + tilt * cell * cols
    if frame:
        z[0, :] = z[-1, :] = z[:, 0] = z[:, -1] = NODATA
    return Grid(z, 500000.0, 5200000.0, cell, NODATA, None), rc


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class StreamLines(unittest.TestCase):
    """0.4.2: watershed.stream_lines, the D8 channels draining at least a threshold area, as polylines."""

    def test_the_valley_channel_is_one_line_along_its_row(self):
        g, rc = valley()
        lines, info = W.stream_lines(g, 20 * 900.0)                    # channels that drain 20 cells or more
        self.assertGreaterEqual(len(lines), 1)
        self.assertEqual(info["lines"], len(lines))
        pts = np.vstack([np.asarray(l) for l in lines])
        ys = g.xy(rc, 5)[1]
        self.assertTrue((np.abs(pts[:, 1] - ys) < 1.5 * g.dx).mean() > 0.9)       # on the channel row (V-valley)
        self.assertGreater(info["length_m"], 0.8 * (g.nx - 4) * g.dx)
        # the line runs downstream: west (the valley drains west), start east of its end
        longest = max(lines, key=lambda l: len(l))
        self.assertGreater(longest[0][0], longest[-1][0])

    def test_a_bigger_threshold_gives_a_shorter_network_and_a_huge_one_none(self):
        g, _ = valley()
        _, small = W.stream_lines(g, 4 * 900.0)
        _, big = W.stream_lines(g, 60 * 900.0)
        self.assertGreater(small["length_m"], big["length_m"])
        lines, none = W.stream_lines(g, 1e12)
        self.assertEqual((lines, none["length_m"]), ([], 0.0))


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Delineation(unittest.TestCase):
    def test_valley_drains_to_its_west_end(self):
        g, rc = valley()
        x, y = g.xy(rc, 1 + 1)
        res = W.delineate(g, x, y, snap_m=60.0)
        self.assertFalse(res["touches_edge"])
        inner = (g.nx - 2) * (g.ny - 2)
        self.assertGreater(res["mask"].sum(), 0.95 * inner)          # nearly the whole valley
        self.assertLessEqual(res["mask"].sum(), inner)
        self.assertAlmostEqual(res["area_m2"], res["mask"].sum() * 900.0)
        self.assertAlmostEqual(res["area_sqmi"], res["area_m2"] / 2589988.110336)
        self.assertFalse(res["mask"][0, :].any())                    # no-data frame is never in the basin

    def test_a_point_half_way_gets_the_upstream_part_only(self):
        g, rc = valley()
        full = W.delineate(g, *g.xy(rc, 2), snap_m=60.0)
        half = W.delineate(g, *g.xy(rc, g.nx // 2), snap_m=60.0, filled=full["filled"])
        self.assertLess(half["mask"].sum(), 0.7 * full["mask"].sum())
        self.assertGreater(half["mask"].sum(), 0.3 * full["mask"].sum())
        self.assertTrue((half["mask"] <= full["mask"]).all())         # nested basins
        self.assertEqual(half["pour_rc"][0], rc)                      # on the channel row

    def test_snap_moves_an_off_channel_point_to_the_channel(self):
        g, rc = valley()
        x, y = g.xy(rc + 3, g.nx // 2)                                # 90 m off the channel
        res = W.delineate(g, x, y, snap_m=150.0)
        self.assertEqual(res["pour_rc"][0], rc)
        self.assertGreaterEqual(res["snapped_from_m"], 85.0)           # at least the 90 m to the channel row
        self.assertLessEqual(res["snapped_from_m"], 150.0)
        res0 = W.delineate(g, x, y, snap_m=0.0)                       # radius 0: no snapping
        self.assertEqual(res0["pour_rc"], g.rc(x, y))
        self.assertLess(res0["mask"].sum(), 20)

    def test_edge_touch_is_flagged(self):
        g, rc = valley(frame=False)                                   # no frame: the basin reaches the array edge
        res = W.delineate(g, *g.xy(rc, 3), snap_m=60.0)
        self.assertTrue(res["touches_edge"])
        self.assertIn("WARNING", " ".join(W.describe(res)))

    def test_flat_reservoir_is_crossed(self):
        g, rc = valley()
        z = g.data.copy()
        z[rc - 1:rc + 2, 20:30] = z[rc, 20]                           # a flat pond in the channel (a lidar DEM does this)
        res = W.delineate(Grid(z, g.x0, g.y0, g.dx, NODATA, None), *g.xy(rc, 2), snap_m=60.0)
        self.assertGreater(res["mask"][:, 31:40].sum(), 0)            # upstream of the pond is still in the basin

    def test_outside_the_dem_is_an_error(self):
        g, rc = valley()
        with self.assertRaises(W.WatershedError):
            W.delineate(g, g.x0 - 1000.0, g.y0, snap_m=30.0)
        with self.assertRaises(W.WatershedError):
            W.delineate(g, *g.xy(0, 0), snap_m=0.0)                   # a no-data cell

    def test_describe_compares_with_the_nid_area(self):
        g, rc = valley()
        res = W.delineate(g, *g.xy(rc, 2), snap_m=60.0)
        text = " ".join(W.describe(res, 2 * res["area_sqmi"]))
        self.assertIn("delineated / NID = 0.50", text)

    def test_accumulation_of_a_chain(self):
        nxt = np.array([1, 2, 3, -1], dtype=np.int64)
        acc, order = W.accumulate(nxt, np.ones(4, bool))
        self.assertEqual(list(acc), [1, 2, 3, 4])
        self.assertEqual([list(o) for o in order], [[0], [1], [2], [3]])

    def test_snap_picks_the_nearest_stream_cell_not_the_far_edge(self):
        acc = np.array([[1, 1, 1, 1, 1], [10, 20, 30, 40, 50], [1, 1, 1, 1, 1]], float)
        r, c, top = W.snap_to_accumulation(acc, (0, 4), 3, frac=0.95)  # the max (50) is in the window: nearest >= 47.5
        self.assertEqual((r, c, top), (1, 4, 50.0))
        r, c, top = W.snap_to_accumulation(acc, (0, 2), 2, frac=0.5)
        self.assertEqual((r, c), (1, 2))

    def test_polygon_wkt_has_the_basin_area(self):
        g, rc = valley()
        res = W.delineate(g, *g.xy(rc, 2), snap_m=60.0)
        geom = ogr.CreateGeometryFromWkt(W.mask_to_polygon_wkt(res["mask"], g))
        self.assertAlmostEqual(geom.GetArea(), res["area_m2"], delta=1.0)


def tiff_bytes(w, h, bbox, epsg, value):
    path = "/vsimem/fake3dep_{}.tif".format(id(bbox))
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((bbox[0], (bbox[2] - bbox[0]) / w, 0, bbox[3], 0, -(bbox[3] - bbox[1]) / h))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(np.full((h, w), value, dtype="float32"))
    ds.FlushCache()
    ds = None
    f = gdal.VSIFOpenL(path, "rb")
    gdal.VSIFSeekL(f, 0, 2)
    n = gdal.VSIFTellL(f)
    gdal.VSIFSeekL(f, 0, 0)
    data = gdal.VSIFReadL(1, n, f)
    gdal.VSIFCloseL(f)
    gdal.Unlink(path)
    return data


class _Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Fetch(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.tmp = tempfile.mkdtemp()

        def opener(url, timeout=None):
            q = parse_qs(urlparse(url).query)
            self.calls.append(url)
            w, h = (int(v) for v in q["size"][0].split(","))
            bbox = tuple(float(v) for v in q["bbox"][0].split(","))
            return _Resp(tiff_bytes(w, h, bbox, int(q["imageSR"][0]), 300.0))
        demfetch.OPENER = opener

    def tearDown(self):
        demfetch.OPENER = None

    def test_fetches_and_mosaics_to_one_geotiff(self):
        r = demfetch.fetch(-106318.83, 2666546.5, 1000.0, 10.0, self.tmp)
        self.assertTrue(r["path"].endswith("dem_3dep_10m_5070.tif"))
        ds = gdal.Open(r["path"])
        self.assertEqual((ds.RasterXSize, ds.RasterYSize), (200, 200))
        self.assertAlmostEqual(float(ds.GetRasterBand(1).ReadAsArray().mean()), 300.0)
        self.assertIn("5070", ds.GetProjection())
        self.assertTrue(all("elevation.nationalmap.gov" in u for u in self.calls))
        self.assertEqual(os.listdir(self.tmp), [os.path.basename(r["path"])])    # tiles and the vrt are tidied away
        self.assertIn("3D Elevation Program", r["citation"])

    def test_too_big_a_request_is_refused_before_any_download(self):
        with self.assertRaises(demfetch.DemFetchError) as cm:
            demfetch.fetch(0.0, 0.0, 50000.0, 1.0, self.tmp)
        self.assertIn("million cells", str(cm.exception))
        self.assertEqual(self.calls, [])

    def test_a_failing_service_is_a_clear_error(self):
        def bad(url, timeout=None):
            return _Resp(b"<html>nope</html>")
        demfetch.OPENER = bad
        with self.assertRaises(demfetch.DemFetchError) as cm:
            demfetch.fetch(0.0, 0.0, 500.0, 10.0, self.tmp)
        self.assertIn("3DEP", str(cm.exception))


US_FT = 0.3048                                                 # metres per international foot (EPSG:2265: ND uses ft)


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class FeetDem(unittest.TestCase):
    """2026-11-20: a DEM in a feet CRS (ND State Plane, EPSG:2265) gives the same basin area in m2 as the metre DEM."""

    def _feet_copy(self, g):
        return Grid(g.data.copy(), g.x0 / US_FT, g.y0 / US_FT, g.dx / US_FT, NODATA, None)

    def test_area_snap_and_cell_size_are_in_metres(self):
        g, rc = valley()
        gf = self._feet_copy(g)
        x, y = g.xy(rc, 2)
        ref = W.delineate(g, x, y, snap_m=60.0)
        got = W.delineate(gf, x / US_FT, y / US_FT, snap_m=60.0, unit_m=US_FT)
        self.assertTrue((got["mask"] == ref["mask"]).all())
        self.assertAlmostEqual(got["area_m2"], ref["area_m2"], delta=1e-6 * ref["area_m2"])
        self.assertAlmostEqual(got["cell_m"], 30.0, places=6)
        self.assertAlmostEqual(got["snapped_from_m"], ref["snapped_from_m"], places=6)
        wrong = W.delineate(gf, x / US_FT, y / US_FT, snap_m=60.0)    # the old reading: ft2 taken as m2
        self.assertGreater(wrong["area_m2"] / ref["area_m2"], 10.7)

    def test_read_dem_of_an_epsg_2265_geotiff(self):
        try:
            from qgis.core import QgsCoordinateReferenceSystem
            from damit_pmp.algorithms import ws_algs
        except ImportError:
            self.skipTest("QGIS not installed")
        g, rc = valley()
        gf = self._feet_copy(g)
        d = tempfile.mkdtemp()
        path = os.path.join(d, "dem_ft.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, gf.nx, gf.ny, 1, gdal.GDT_Float64)
        ds.SetGeoTransform((1900000.0, gf.dx, 0.0, 700000.0, 0.0, -gf.dx))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(2265)                                     # NAD83 / North Dakota North (ft)
        ds.SetProjection(srs.ExportToWkt())
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(NODATA)
        b.WriteArray(gf.data)
        ds = None
        grid, wkt, crs, unit_m = ws_algs.read_dem(path)
        self.assertAlmostEqual(unit_m, US_FT, places=9)                 # EPSG:2265 is international feet
        self.assertAlmostEqual(ws_algs.metres_per_map_unit(QgsCoordinateReferenceSystem("EPSG:26914")), 1.0)
        self.assertAlmostEqual(ws_algs.metres_per_map_unit(QgsCoordinateReferenceSystem("EPSG:2265")), US_FT, places=9)
        self.assertAlmostEqual(grid.dx, gf.dx, places=6)                # the grid stays in feet (its CRS's units)
        res = W.delineate(grid, *grid.xy(rc, 2), snap_m=60.0, unit_m=unit_m)
        self.assertAlmostEqual(res["area_m2"], res["mask"].sum() * 900.0, delta=1e-3)


if __name__ == "__main__":
    unittest.main()
