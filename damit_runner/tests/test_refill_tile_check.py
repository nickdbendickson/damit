"""DamIT Runner 0.7.10: DamSafety #397 (DWR_Plugins 0ca91de6, Runner 3.20.14) - a 3DEP refill without
ground is refused, not filled in as a 0 m pit, and long routed hydrographs never repeat a time in the
model file. DamSafety's tests (test_dem_refill_crs_proxy.py and run_tests.py) with DamIT's import
paths (compat.netproxy instead of damsuite.netproxy). Pure Python; the tile test needs GDAL. No model."""
import os
import sys
import tempfile
import unittest
import urllib.parse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.compat import netproxy  # noqa: E402
from damit_runner.core import breach as br  # noqa: E402
from damit_runner.core import dem_refill  # noqa: E402

FAKE_TIFF = b"II*\x00" + b"\x00" * 2000


class _FakeResp(object):
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _tif(path, arr, nodata=None):
    from osgeo import gdal, osr
    a = np.asarray(arr, dtype="float32")
    ds = gdal.GetDriverByName("GTiff").Create(path, a.shape[1], a.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform((700000.0, 30.0, 0.0, 4840000.0, 0.0, -30.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(26916)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    if nodata is not None:
        b.SetNoDataValue(nodata)
    b.WriteArray(a)
    ds = None
    return path


class RefillTileCheck(unittest.TestCase):
    def test_refill_asks_3dep_to_mark_cells_without_ground(self):
        # 3.20.14: without noData, 3DEP writes 0 m where it has no ground, and 0 m was filled in
        seen = {}

        def fake_urlopen(req, timeout=60, settings=None):
            seen["url"] = req.full_url if hasattr(req, "full_url") else str(req)
            return _FakeResp(FAKE_TIFF)

        real = netproxy.urlopen
        netproxy.urlopen = fake_urlopen
        try:
            dem_refill.fetch_3dep((100.0, 200.0, 1100.0, 1200.0), 10.0,
                                  os.path.join(tempfile.mkdtemp(), "refill.tif"), crs=26916)
        finally:
            netproxy.urlopen = real
        q = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
        self.assertEqual(q.get("noData"), [str(dem_refill.NODATA_OUT)])

    def test_refill_tile_without_ground_is_refused(self):
        try:
            from osgeo import gdal  # noqa: F401
        except ImportError:
            self.skipTest("no GDAL (osgeo) in this Python")
        d = tempfile.mkdtemp()
        for name, arr, nd in (("zeros", np.zeros((4, 5)), None),
                              ("nodata_tagged", np.full((4, 5), -9999.0), -9999.0),
                              ("nodata_untagged", np.full((4, 5), -9999.0), None),
                              ("flat", np.full((4, 5), 191.87), None)):
            path = _tif(os.path.join(d, name + ".tif"), arr, nd)
            with self.assertRaises(IOError, msg=name) as cm:
                dem_refill.check_tile(path)
            self.assertIn("ground", str(cm.exception), name)
        ok = np.array([[190.0, 191.5, 193.0], [189.0, -9999.0, 192.0]])
        dem_refill.check_tile(_tif(os.path.join(d, "ok.tif"), ok, -9999.0))    # ground, with a hole

    def test_long_routed_hydrograph_has_increasing_model_file_times(self):
        rng = np.random.default_rng(7)
        t = np.sort(np.concatenate([rng.uniform(0.0, 96 * 3600.0, 6000),
                                    30.0 * np.arange(1, 2000) + 3e-5,
                                    [1234.5, 1234.5 + 1e-6, 5000.0, 5000.0]]))
        q = 1000.0 * np.exp(-((t - 40 * 3600.0) / (8 * 3600.0)) ** 2) + 50.0
        h = br.Hydrograph(t_s=t, q_cms=q, method="routed")
        tr, qr = h.resampled(30.0)
        printed = np.array([float("{:.4f}".format(x)) for x in tr])
        self.assertTrue(np.all(np.diff(printed) > 0), "repeated time in the model file")
        self.assertAlmostEqual(qr.max() / q.max(), 1.0, delta=1e-6)
        self.assertEqual(qr[-1], 0.0)
        self.assertEqual(tr[-2], t[-1])


if __name__ == "__main__":
    unittest.main()
