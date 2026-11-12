"""damit_pmp 0.4.0: temporal patterns (temporal.py: NRCS 24-hour types, NOAA Atlas 14 HDSC temporal distributions) and
initial + constant losses (storm.py). Needs numpy (GDAL for the shapefile test); no QGIS, no network: the HDSC files
come from a fake downloader, the curve file is the real HDSC mw_2_24h_temporal.csv (fixtures/)."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

try:
    import numpy as np
    HAVE = True
except ImportError:                                            # pragma: no cover
    HAVE = False
try:
    from osgeo import ogr, osr
    HAVE_OGR = True
except ImportError:                                            # pragma: no cover
    HAVE_OGR = False

if HAVE:
    from damit_pmp import atlas14 as A
    from damit_pmp import storm as S
    from damit_pmp import temporal as T

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def slurp(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def fargo_pf():
    return A.parse(slurp("pfds_pds_english_fargo_nd.txt"))


@unittest.skipUnless(HAVE, "numpy not installed")
class NrcsCurves(unittest.TestCase):
    def test_every_type_is_a_cumulative_0_to_1_24_hour_curve(self):
        for kind in ("I", "IA", "II", "III"):
            h, f = T.nrcs_curve(kind)
            self.assertEqual((h[0], h[-1], f[0], f[-1]), (0.0, 24.0, 0.0, 1.0), kind)
            self.assertTrue((np.diff(f) > 0).all(), kind)

    def test_type_ii_published_ordinates(self):
        h, f = T.nrcs_curve("II")
        at = dict(zip(h, f))
        self.assertEqual((at[11.5], at[12.0], at[12.5]), (0.283, 0.663, 0.735))        # TR-55 Exhibit 4-II
        self.assertAlmostEqual(at[12.0] - at[11.75], 0.306)
        self.assertAlmostEqual(at[12.0] - at[11.0], 0.428, places=3)                   # the steep hour

    def test_type_peaks_are_where_they_should_be(self):
        peak_hour = {}
        for kind in ("I", "IA", "II", "III"):
            h, f = T.nrcs_curve(kind)
            peak_hour[kind] = h[1:][np.argmax(np.diff(f) / np.diff(h))]
        self.assertEqual(peak_hour["II"], 12.0)
        self.assertEqual(peak_hour["III"], 12.0)
        self.assertLessEqual(peak_hour["I"], 11.0)
        self.assertLessEqual(peak_hour["IA"], 9.0)

    def test_record_says_shape_only_and_cites(self):
        rec = T.nrcs_record("II")
        self.assertIn("shape option only", rec["note"])
        self.assertIn("Technical Release 55", rec["citation"])


@unittest.skipUnless(HAVE, "numpy not installed")
class Patterns(unittest.TestCase):
    def test_check_pattern_names_the_durations(self):
        T.check_pattern("alternating", 5)
        T.check_pattern("atlas14", 1440)
        T.check_pattern("atlas14", 360, "6-hr")
        T.check_pattern("nrcs2", 1440)
        with self.assertRaises(T.TemporalError) as cm:
            T.check_pattern("atlas14", 180, "3-hr")
        self.assertIn("6-, 12-, 24- and 96-hour", str(cm.exception))
        with self.assertRaises(T.TemporalError) as cm:
            T.check_pattern("nrcs3", 720, "12-hr")
        self.assertIn("Type III", str(cm.exception))
        with self.assertRaises(T.TemporalError):
            T.check_pattern("nope", 1440)

    def test_url_is_the_hdsc_pattern(self):
        self.assertEqual(T.temporal_url("mw", 2, 24), "https://hdsc.nws.noaa.gov/pub/hdsc/data/mw/mw_2_24h_temporal.csv")
        with self.assertRaises(T.TemporalError):
            T.temporal_url("se", 2, 24)                       # Volume 2: not wired, says so
        with self.assertRaises(T.TemporalError):
            T.temporal_url("mw", 2, 48)

    def test_parse_the_real_hdsc_file(self):
        p = T.parse_temporal(slurp("mw_2_24h_temporal.csv"))
        self.assertIn("Volume 8", p["title"])
        self.assertEqual(sorted(p["cases"]), ["all", "first", "fourth", "second", "third"])
        c = p["cases"]["second"]
        self.assertEqual(c["pcts"], [90, 80, 70, 60, 50, 40, 30, 20, 10])
        self.assertEqual((c["hours"][0], c["hours"][-1], len(c["hours"])), (0.0, 24.0, 49))
        h, f = T.curve(p, "second", 50)
        self.assertEqual((f[0], f[-1]), (0.0, 1.0))
        self.assertTrue((np.diff(f) >= 0).all())
        h1, f1 = T.curve(p, "first", 50)
        self.assertGreater(f1[8], f[8])                       # first quartile: more of the rain early
        with self.assertRaises(T.TemporalError):
            T.curve(p, "second", 55)
        self.assertEqual(T.curve(p, "all", 50)[1][-1], 1.0)
        del p["cases"]["third"]
        with self.assertRaises(T.TemporalError):
            T.curve(p, "third", 50)

    def test_junk_is_refused(self):
        with self.assertRaises(T.TemporalError):
            T.parse_temporal("hello\nworld\n")

    def test_rows_from_curve_sums_to_the_atlas_depth(self):
        h, f = T.nrcs_curve("II")
        rows = T.rows_from_curve(h, f, 6.34, 1440, 30)
        self.assertEqual(len(rows), 48)
        self.assertEqual(rows[-1][0], 1440)
        self.assertEqual(rows[-1][2], 6.34)                   # exactly the storm total, not 6.3401
        self.assertAlmostEqual(sum(r[1] for r in rows), 6.34, places=3)
        peak = max(rows, key=lambda r: r[1])
        self.assertEqual(peak[0], 720)                        # the half hour ending at hour 12: 0.283 -> 0.663 of Type II
        with self.assertRaises(T.TemporalError):
            T.rows_from_curve(h, f, 6.34, 720, 30)            # a 24 h curve for a 12 h storm


class FakeDownload:
    """The downloader hook: writes the real HDSC file (any area) or a zip holding a tiny shapefile."""
    def __init__(self, shp_zip=None):
        self.urls = []
        self.shp_zip = shp_zip

    def __call__(self, url, dest):
        self.urls.append(url)
        if url.endswith(".csv"):
            shutil.copyfile(os.path.join(FIX, "mw_2_24h_temporal.csv"), dest)
        elif url.endswith(".zip") and self.shp_zip:
            shutil.copyfile(self.shp_zip, dest)
        else:
            raise IOError("unexpected URL " + url)


def make_area_zip(path, boxes):
    """A zip with Vol_8_Temporal_Regions.shp: one polygon per (region, (x0, y0, x1, y1))."""
    import zipfile
    d = tempfile.mkdtemp()
    ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(d)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4269)
    lyr = ds.CreateLayer("Vol_8_Temporal_Regions", srs, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("Region", ogr.OFTInteger))
    for region, (x0, y0, x1, y1) in boxes:
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("Region", region)
        f.SetGeometry(ogr.CreateGeometryFromWkt("POLYGON(({0} {1},{2} {1},{2} {3},{0} {3},{0} {1}))".format(x0, y0, x1, y1)))
        lyr.CreateFeature(f)
    ds = None
    with zipfile.ZipFile(path, "w") as z:
        for fn in os.listdir(d):
            z.write(os.path.join(d, fn), fn)
    shutil.rmtree(d)


@unittest.skipUnless(HAVE, "numpy not installed")
class Atlas14Files(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_fetch_caches_and_records_a_hash(self):
        dl = FakeDownload()
        url = T.temporal_url("mw", 2, 24)
        p, rec = T.fetch_file(url, self.cache, dl)
        self.assertFalse(rec["from_cache"])
        self.assertEqual(len(rec["sha256"]), 64)
        p2, rec2 = T.fetch_file(url, self.cache, dl)
        self.assertTrue(rec2["from_cache"])
        self.assertEqual(rec2["sha256"], rec["sha256"])
        self.assertEqual(len(dl.urls), 1)
        with self.assertRaises(T.TemporalError):
            T.fetch_file(T.temporal_url("mw", 3, 24), self.cache, dl, offline=True)

    def test_atlas14_curve_with_the_area_given(self):
        h, f, rec = T.atlas14_curve(-96.9, 46.9, "mw", 24, "second", 50, self.cache, FakeDownload(), area=2)
        self.assertEqual((h[-1], f[-1]), (24.0, 1.0))
        self.assertEqual((rec["area"], rec["quartile"], rec["percent_of_occurrence"], rec["duration_hr"]), (2, "second", 50, 24))
        self.assertEqual(rec["area_from"], "user choice")
        self.assertIn("Shape only", rec["note"])
        self.assertIn("hdsc.nws.noaa.gov", rec["file"]["url"])
        self.assertIn("Atlas 14 Volume 8", rec["citation"])
        json.dumps(rec)                                        # goes into the JSON as it is

    @unittest.skipUnless(HAVE_OGR, "GDAL not installed")
    def test_area_is_found_from_the_shapefile(self):
        z = os.path.join(self.cache, "shp.zip")
        make_area_zip(z, [(1, (-98, 45, -97.5, 48)), (2, (-97.5, 45, -96, 48)), (3, (-96, 45, -94, 48))])
        dl = FakeDownload(shp_zip=z)
        h, f, rec = T.atlas14_curve(-96.9, 46.9, "mw", 24, "second", 50, self.cache, dl)
        self.assertEqual(rec["area"], 2)
        self.assertEqual(rec["area_from"], "HDSC shapefile point-in-polygon")
        self.assertTrue(any(u.endswith("mw_2_24h_temporal.csv") for u in dl.urls))
        self.assertTrue(any("Vol8_Temporals_Shapefiles.zip" in u for u in dl.urls))
        with self.assertRaises(T.TemporalError) as cm:
            T.atlas14_curve(-120.0, 46.9, "mw", 24, "second", 50, self.cache, dl)
        self.assertIn("outside", str(cm.exception))

    def test_unwired_volume_says_so(self):
        with self.assertRaises(T.TemporalError) as cm:
            T.atlas14_curve(-90.0, 30.0, "se", 24, "second", 50, self.cache, FakeDownload(), area=1)
        self.assertIn("Volume 8", str(cm.exception))


@unittest.skipUnless(HAVE, "numpy not installed")
class Losses(unittest.TestCase):
    ROWS = [(30, 0.5, 0.5), (60, 1.0, 1.5), (90, 2.0, 3.5), (120, 0.5, 4.0)]

    def test_zero_losses_change_nothing(self):
        t = S.apply_losses(self.ROWS)
        self.assertEqual([r[3] for r in t], [r[1] for r in self.ROWS])
        self.assertEqual([r[2] for r in t], [0.0] * 4)

    def test_initial_loss_then_constant_rate(self):
        t = S.apply_losses(self.ROWS, initial=0.8, constant_rate=0.4)      # in / hr: 0.2 in per 30 min step
        # step 1: 0.5 all lost (0.3 left); step 2: 0.3 lost to the initial loss, then 0.2 constant; ...
        self.assertEqual([r[2] for r in t], [0.5, 0.5, 0.2, 0.2])
        self.assertEqual([r[3] for r in t], [0.0, 0.5, 1.8, 0.3])
        s = S.loss_summary(t, "in")
        self.assertEqual((s["gross_in"], s["loss_in"], s["excess_in"]), (4.0, 1.4, 2.6))
        self.assertAlmostEqual(s["runoff_fraction"], 0.65)

    def test_constant_loss_never_exceeds_the_rain(self):
        t = S.apply_losses(self.ROWS, initial=0.0, constant_rate=10.0)
        self.assertEqual([r[3] for r in t], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(sum(r[2] for r in t), 4.0)

    def test_loss_never_goes_negative_or_nonsense(self):
        with self.assertRaises(S.LossError):
            S.apply_losses(self.ROWS, initial=-1)
        with self.assertRaises(S.LossError):
            S.apply_losses(self.ROWS, constant_rate=-0.1)

    def test_units(self):
        self.assertEqual(S.to_unit(1.0, "in", "mm"), 25.4)
        self.assertAlmostEqual(S.to_unit(25.4, "mm", "in"), 1.0)
        self.assertEqual(S.to_unit(3.0, "in", "in"), 3.0)


@unittest.skipUnless(HAVE, "numpy not installed")
class Build(unittest.TestCase):
    def test_alternating_is_the_existing_function(self):
        pf = fargo_pf()
        self.assertEqual(S.build(pf, 100, 1440, 60), A.alternating_block(pf, 100, 1440, 60))

    def test_every_pattern_has_the_atlas_14_depth(self):
        pf = fargo_pf()
        total = A.depth_at(pf, 1440, 100)
        h, f = T.nrcs_curve("II")
        for pat in ("alternating", "nrcs2"):
            rows = S.build(pf, 100, 1440, 60, pat, "24-hr", (h, f) if pat != "alternating" else None)
            self.assertAlmostEqual(rows[-1][2], total, places=3, msg=pat)
        with self.assertRaises(T.TemporalError):
            S.build(pf, 100, 1440, 60, "atlas14", "24-hr", None)             # a curve is required
        with self.assertRaises(T.TemporalError):
            S.build(pf, 100, 720, 60, "nrcs2", "12-hr", (h, f))              # NRCS is 24 h only

    def test_pattern_changes_the_shape_not_the_depth(self):
        pf = fargo_pf()
        h, f = T.nrcs_curve("II")
        a = S.build(pf, 100, 1440, 30)
        n = S.build(pf, 100, 1440, 30, "nrcs2", "24-hr", (h, f))
        self.assertAlmostEqual(a[-1][2], n[-1][2], places=3)
        self.assertNotEqual([r[1] for r in a], [r[1] for r in n])


@unittest.skipUnless(HAVE, "numpy not installed")
class OnlyHdsc(unittest.TestCase):
    def test_the_temporal_module_names_no_other_depth_source(self):
        with open(os.path.join(ROOT, "damit_pmp", "temporal.py"), encoding="utf-8") as fh:
            src = fh.read()
        for h in set(re.findall(r"https?://([\w.\-]+)", src)):
            self.assertIn(h, ("hdsc.nws.noaa.gov", "www.nrcs.usda.gov", "directives.sc.egov.usda.gov", "www.nws.noaa.gov"), h)


if __name__ == "__main__":
    unittest.main()
