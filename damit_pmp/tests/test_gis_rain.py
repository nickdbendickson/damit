"""DamIT PMP 0.3.0: Atlas 14 GIS grid URLs / cache / clip / scaling and the rain-on-grid export.

Pure Python + (for the clip tests) GDAL and numpy; no QGIS and no network. A real NOAA download is
checked only when DAMIT_NETWORK_TESTS=1 (the DWR-2801 cell of mw100yr24ha is 6342 = 6.342 in)."""
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from damit_pmp import atlas14 as A  # noqa: E402
from damit_pmp import gisgrid as G  # noqa: E402
from damit_pmp import rainexport as R  # noqa: E402

try:
    import numpy as np
    from osgeo import gdal  # noqa: F401
    HAVE_GDAL = True
except ImportError:                                            # pragma: no cover
    HAVE_GDAL = False

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
# the duration menu of https://hdsc.nws.noaa.gov/pfds/pfds_gis.html (copied 2026-11-12)
NOAA_DUR_MENU = ["05m", "10m", "15m", "30m", "60m", "02h", "03h", "06h", "12h", "24h", "48h", "03d", "04d", "07d",
                 "10d", "20d", "30d", "45d", "60d"]


def fake_noaa_zip(path, values, x0=-97.5, y0=46.9, cell=0.0083333, nodata=-9, name="mw100yr24ha"):
    """A zip shaped like NOAA's: <name>.asc (ESRI ASCII, thousandths of an inch), .prj and .xml."""
    nr, nc = len(values), len(values[0])
    body = "ncols {}\nnrows {}\nxllcorner {}\nyllcorner {}\ncellsize {}\nNODATA_value {}\n".format(
        nc, nr, x0, y0, cell, nodata) + "\n".join(" ".join(str(v) for v in row) for row in values) + "\n"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name + ".asc", body)
        z.writestr(name + ".prj", 'GEOGCS["GCS_North_American_1983"]')
        z.writestr(name + ".xml", "<metadata><title>Precipitation Frequency for Midwestern states, USA - NOAA Atlas 14 "
                                  "Volume 8</title><pubdate>20130415</pubdate></metadata>")


def _slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Urls(unittest.TestCase):
    def test_dwr_2801_example(self):
        self.assertEqual(G.grid_url("mw", 100, "24-hr"), "https://hdsc.nws.noaa.gov/pub/hdsc/data/mw/mw100yr24ha.zip")

    def test_duration_codes_match_the_noaa_menu(self):
        self.assertEqual([G.DUR_CODES[d] for d in G.DURATION_LABELS], NOAA_DUR_MENU)
        self.assertEqual(G.DUR_CODES["2-day"], "48h")                  # not 02d

    def test_choices(self):
        self.assertTrue(G.zip_name("mw", 500, "6-hr").endswith("mw500yr06ha.zip"))
        self.assertEqual(G.zip_name("mw", 1, "60-min"), "mw1yr60ma.zip")
        self.assertEqual(G.zip_name("orb", 1000, "60-day", "upper90", "ams"), "orb1000yr60dau_ams.zip")
        self.assertEqual(G.zip_name("tx", 2, "5-min", "lower90"), "tx2yr05mal.zip")

    def test_frequencies_checked(self):
        with self.assertRaises(A.Atlas14Error):
            G.zip_name("mw", 3, "24-hr")
        with self.assertRaises(A.Atlas14Error):
            G.zip_name("mw", 1, "24-hr", series="ams")                  # no 1-year AEP file
        with self.assertRaises(A.Atlas14Error):
            G.zip_name("mw", 100, "7-hr")
        with self.assertRaises(A.Atlas14Error):
            G.zip_name("zz", 100, "24-hr")
        for y in A.PDS_ARI:
            G.zip_name("mw", y, "24-hr")
        for y in A.AMS_AEP_YEARS:
            G.zip_name("mw", y, "24-hr", series="ams")

    def test_round_trip_every_combination(self):
        n = 0
        for d in G.DURATION_LABELS:
            for series, ys in (("pds", A.PDS_ARI), ("ams", A.AMS_AEP_YEARS)):
                for y in ys:
                    for b, _ in G.BOUNDS:
                        got = G.parse_zip_name(G.zip_name("mw", y, d, b, series))
                        self.assertEqual(got, {"region": "mw", "frequency_years": y, "duration": d, "bound": b,
                                               "series": series})
                        n += 1
        self.assertEqual(n, 19 * 19 * 3)
        self.assertIsNone(G.parse_zip_name("mw100yr24.zip"))

    def test_region_from_pfds(self):
        with open(os.path.join(FIX, "pfds_pds_english_fargo_nd.txt"), "rb") as fh:
            self.assertEqual(G.region_from_pfds(A.parse(fh.read())), "mw")
        with self.assertRaises(A.Atlas14Error):
            G.region_from_pfds({"region_code": "xx", "region": "Nowhere"})


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def dl(self, url, dest):
        self.calls.append(url)
        fake_noaa_zip(dest, [[6342, 6350], [6400, -9]])

    def test_download_once_then_cache(self):
        p, rec = G.fetch_zip("mw", 100, "24-hr", "estimate", "pds", self.tmp, self.dl)
        self.assertFalse(rec["from_cache"])
        self.assertEqual(rec["url"], "https://hdsc.nws.noaa.gov/pub/hdsc/data/mw/mw100yr24ha.zip")
        self.assertEqual(len(rec["sha256"]), 64)
        p2, rec2 = G.fetch_zip("mw", 100, "24-hr", "estimate", "pds", self.tmp, self.dl)
        self.assertTrue(rec2["from_cache"])
        self.assertEqual(rec2["fetched"], rec["fetched"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(p, p2)

    def test_offline(self):
        with self.assertRaises(A.Atlas14Error) as cm:
            G.fetch_zip("mw", 100, "24-hr", "estimate", "pds", self.tmp, self.dl, offline=True)
        self.assertIn("offline", str(cm.exception))
        self.assertEqual(self.calls, [])
        G.fetch_zip("mw", 100, "24-hr", "estimate", "pds", self.tmp, self.dl)
        G.fetch_zip("mw", 100, "24-hr", "estimate", "pds", self.tmp, self.dl, offline=True)     # cached: fine

    def test_404_is_not_published(self):
        from damit_core.lib.http import HttpError

        def nf(url, dest):
            raise HttpError(url, 404, "Not Found")
        with self.assertRaises(G.NotPublished) as cm:
            G.fetch_zip("sa", 100, "24-hr", "estimate", "ams", self.tmp, nf)
        self.assertIn("has not published sa100yr24ha_ams.zip", str(cm.exception))

    def test_network_error_passes_through(self):
        from damit_core.lib.http import HttpError

        def down(url, dest):
            raise HttpError(url, None, "network is unreachable")
        with self.assertRaises(IOError):
            G.fetch_zip("mw", 100, "24-hr", "estimate", "pds", self.tmp, down)

    def test_not_a_zip(self):
        def junk(url, dest):
            with open(dest, "w") as fh:
                fh.write("<html>captive portal</html>")
        with self.assertRaises(A.Atlas14Error):
            G.fetch_zip("mw", 100, "24-hr", "estimate", "pds", self.tmp, junk)
        self.assertFalse(os.path.exists(G.cache_zip_path(self.tmp, "mw", "mw100yr24ha.zip")))


@unittest.skipUnless(HAVE_GDAL, "GDAL / numpy not importable")
class Clip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.zip = os.path.join(self.tmp, "mw100yr24ha.zip")
        # 4 x 4 cells, top-left (-97.5, 46.9 + 4 * 0.0083333); thousandths of an inch; one NODATA cell
        self.vals = [[6300, 6310, 6320, 6330], [6340, 6342, 6350, 6360], [6400, 6410, 6420, -9], [6500, 6510, 6520, 6530]]
        fake_noaa_zip(self.zip, self.vals)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_scale_thousandths_to_inches(self):
        arr, gt, epsg = G.read_clip(self.zip)
        self.assertEqual(arr.dtype.name, "float32")
        self.assertAlmostEqual(float(arr[1, 1]), 6.342, places=4)                  # 6342 -> 6.342 in
        self.assertEqual(float(arr[2, 3]), G.NODATA_OUT)                           # -9 is empty
        self.assertEqual(epsg, 4269)
        st = G.array_stats(arr)
        self.assertEqual(st["cells"], 15)
        self.assertEqual((st["min"], st["max"]), (6.3, 6.53))

    def test_window_and_value_at(self):
        # the cell holding 6342: column 1, row 1 -> lon -97.4917..-97.4833, lat from the top
        top = 46.9 + 4 * 0.0083333
        lon, lat = -97.5 + 1.5 * 0.0083333, top - 1.5 * 0.0083333
        arr, gt, _ = G.read_clip(self.zip, (lon - 0.001, lat - 0.001, lon + 0.001, lat + 0.001))
        self.assertEqual(arr.shape, (1, 1))
        self.assertAlmostEqual(G.value_at(arr, gt, lon, lat), 6.342, places=4)
        self.assertIsNone(G.value_at(arr, gt, lon + 1, lat))

    def test_outside_the_grid_fails_clearly(self):
        with self.assertRaises(A.Atlas14Error) as cm:
            G.read_clip(self.zip, (-100.0, 40.0, -99.0, 41.0))
        self.assertIn("outside this Atlas 14 grid", str(cm.exception))

    def test_all_nodata_is_a_coverage_error(self):
        fake_noaa_zip(self.zip, [[-9, -9], [-9, -9]])
        with self.assertRaises(A.CoverageError):
            G.read_clip(self.zip)

    def test_mask_polygon(self):
        top = 46.9 + 4 * 0.0083333
        # a polygon over the left two columns only
        wkt = "POLYGON((-97.5 {t},-97.4834 {t},-97.4834 {b},-97.5 {b},-97.5 {t}))".format(t=top, b=46.9)
        arr, gt, _ = G.read_clip(self.zip, mask_wkt=wkt)
        self.assertEqual(G.array_stats(arr)["cells"], 8)
        self.assertEqual(float(arr[0, 3]), G.NODATA_OUT)

    def test_geotiff_round_trip_and_gridstats(self):
        from osgeo import gdal as g
        from damit_pmp import gridstats
        arr, gt, epsg = G.read_clip(self.zip)
        tif = os.path.join(self.tmp, "out.tif")
        G.write_geotiff(tif, arr, gt, epsg)
        ds = g.Open(tif)
        self.assertEqual(ds.GetRasterBand(1).GetNoDataValue(), G.NODATA_OUT)
        self.assertAlmostEqual(float(ds.GetRasterBand(1).ReadAsArray()[1, 1]), 6.342, places=4)
        # a fetchgrid tif is read as inches (scale 1) only with its sidecar; NOAA's own file keeps 0.001
        self.assertEqual(gridstats.grid_scale(tif, 0.001), 0.001)
        with open(tif + ".json", "w") as fh:
            json.dump({"schema": "damit.pmp.atlas14_gis", "units": "in"}, fh)
        self.assertEqual(gridstats.grid_scale(tif, 0.001), 1.0)
        mid = gridstats.point_value(tif, -97.5 + 1.5 * 0.0083333, 46.9 + 4 * 0.0083333 - 1.5 * 0.0083333,
                                    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                                    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]', 1.0)
        self.assertAlmostEqual(mid, 6.342, places=3)

    def test_zip_metadata(self):
        self.assertEqual(G.zip_metadata(self.zip)["pubdate"], "20130415")


@unittest.skipUnless(HAVE_GDAL, "GDAL / numpy not importable")
class GridNames(unittest.TestCase):
    def test_parse_name(self):
        from damit_pmp import gridstats as S
        self.assertEqual(S.parse_name("mw100yr24ha.asc"), {"region_code": "mw", "frequency_years": 100,
                                                          "duration": "24-hr", "series": "pds"})
        self.assertEqual(S.parse_name("mw100yr48hau.asc")["duration"], "2-day")
        self.assertEqual(S.parse_name("mw100yr48hau.asc")["bound"], "upper90")
        self.assertEqual(S.parse_name("sw1000yr60da_ams.asc"), {"region_code": "sw", "frequency_years": 1000,
                                                               "duration": "60-day", "series": "ams"})
        self.assertEqual(S.parse_name("mw5yr05mal.zip")["duration"], "5-min")
        # every file-name duration maps to an Atlas 14 duration label
        for lab, code in G.DUR_CODES.items():
            self.assertEqual(S.parse_name("mw2yr{}a.asc".format(code))["duration"], lab)


HYETO = """t_end_min,incremental_in,cumulative_in
60,1.0,1.0
120,2.0,3.0
180,0.5,3.5
# alternating block on NOAA Atlas 14 depths; test
# damit_pmp hyetograph: frequency_years=100; storm_min=180; step_min=60; series=pds; depth_unit=in
"""


class Rain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csv = os.path.join(self.tmp, "h.csv")
        with open(self.csv, "w") as fh:
            fh.write(HYETO)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_read_hyetograph_converts_inches_to_mm(self):
        blocks, unit = R.read_hyetograph(self.csv)
        self.assertEqual(unit, "in")
        self.assertEqual([(a, b) for a, b, _ in blocks], [(0, 60), (60, 120), (120, 180)])
        self.assertAlmostEqual(R.total_mm(blocks), 3.5 * 25.4)
        self.assertAlmostEqual(R.total_mm(blocks), 88.9)

    def test_dwr_2801_depth(self):
        self.assertAlmostEqual(6.34 * R.MM_PER_IN, 161.036)

    def test_mm_hyetograph(self):
        p = os.path.join(self.tmp, "m.csv")
        with open(p, "w") as fh:
            fh.write("t_end_min,incremental_mm,cumulative_mm\n30,5,5\n60,10,15\n")
        blocks, unit = R.read_hyetograph(p)
        self.assertEqual(unit, "mm")
        self.assertAlmostEqual(R.total_mm(blocks), 15.0)

    def test_bad_csv(self):
        p = os.path.join(self.tmp, "b.csv")
        with open(p, "w") as fh:
            fh.write("a,b\n1,2\n")
        with self.assertRaises(R.RainError):
            R.read_hyetograph(p)
        with self.assertRaises(R.RainError):
            R.blocks_from_rows([(60, 1.0), (60, 1.0)], "in")                     # time must increase

    def test_rate_mm_per_hr(self):
        blocks, _ = R.read_hyetograph(self.csv)
        pts = R.series(blocks)
        # 1.0 in in one hour = 25.4 mm/hr; 2.0 in -> 50.8; 0.5 in -> 12.7
        self.assertEqual(pts[0], (0, 25.4))
        self.assertEqual(pts[1], (3599, 25.4))
        self.assertEqual(pts[2], (3600, 50.8))
        self.assertAlmostEqual(pts[4][1], 12.7)
        self.assertEqual(pts[-1], (10800, 0.0))

    def test_series_mass(self):
        blocks, _ = R.read_hyetograph(self.csv)
        for ramp in (1, 5, 60):
            self.assertAlmostEqual(R.integrate_mm(R.series(blocks, ramp)), 88.9, delta=88.9 * 0.003)      # a 60 s ramp loses ~ramp * rate / 2
        self.assertAlmostEqual(R.integrate_mm(R.series(blocks, 1)), 88.9, delta=88.9 * 1e-4)

    def test_m_per_s(self):
        self.assertAlmostEqual(R.to_m_per_s(3.6e6), 1.0)                        # 3.6e6 mm/hr = 1 m/s
        self.assertAlmostEqual(R.to_m_per_s(25.4), 25.4 / 3.6e6)
        self.assertAlmostEqual(R.to_m_per_s(1.0), 2.7778e-7, places=10)

    def test_rain_file_format(self):
        blocks, _ = R.read_hyetograph(self.csv)
        pts = R.series(blocks, sim_time_s=4 * 3600)
        txt = R.rain_text(pts, "seconds")
        lines = txt.splitlines()
        self.assertTrue(lines[0].startswith("#"))                               # line 1: comment, ignored by LISFLOOD-FP
        self.assertEqual(lines[1], "{} seconds".format(len(pts)))              # line 2: count and time unit
        self.assertEqual(lines[2], "25.40000 0")                               # then "rate time"
        self.assertEqual(lines[3], "25.40000 3599")
        self.assertEqual(len(lines), 2 + len(pts))
        self.assertTrue(lines[-1].endswith(" 14400") and lines[-1].startswith("0.00000"))
        back = R.parse_rain(txt)
        self.assertEqual(len(back), len(pts))
        for (t0, r0), (t1, r1) in zip(pts, back):
            self.assertEqual(t0, t1)
            self.assertAlmostEqual(r0, r1, places=4)
        self.assertAlmostEqual(R.integrate_mm(back), 88.9, delta=0.01)

    def test_rain_file_hours_and_days(self):
        blocks, _ = R.read_hyetograph(self.csv)
        pts = R.series(blocks, ramp_s=36)
        h = R.rain_text(pts, "hours").splitlines()
        self.assertEqual(h[1].split()[1], "hours")
        self.assertEqual(h[3].split()[1], "0.99")                              # 3564 s
        self.assertAlmostEqual(R.integrate_mm(R.parse_rain(R.rain_text(pts, "hours"))), R.integrate_mm(pts), places=2)
        self.assertAlmostEqual(R.integrate_mm(R.parse_rain(R.rain_text(pts, "days"))), R.integrate_mm(pts), places=2)
        with self.assertRaises(R.RainError):
            R.rain_text(pts, "minutes")

    def test_series_errors(self):
        blocks, _ = R.read_hyetograph(self.csv)
        with self.assertRaises(R.RainError):
            R.series(blocks, ramp_s=0)
        with self.assertRaises(R.RainError):
            R.series(blocks, ramp_s=3600)

    def test_scale_to_grid_depth(self):
        blocks, _ = R.read_hyetograph(self.csv)
        total_in = R.total_mm(blocks) / R.MM_PER_IN
        scaled = R.scale_blocks(blocks, 4.2 / total_in)
        self.assertAlmostEqual(R.total_mm(scaled) / R.MM_PER_IN, 4.2)
        with self.assertRaises(R.RainError):
            R.scale_blocks(blocks, 0)

    def test_export_writes_both_files_and_readme(self):
        blocks, _ = R.read_hyetograph(self.csv)
        rain, anuga = os.path.join(self.tmp, "s.rain"), os.path.join(self.tmp, "s_anuga.csv")
        rec = R.export(blocks, rain, anuga, "seconds", 1, None, source="NOAA Atlas 14 - test", desc="3.5 in over 3 h")
        self.assertAlmostEqual(rec["total_depth_mm"], 88.9, places=3)
        self.assertLess(abs(rec["series_depth_error_pct"]), 0.01)
        self.assertAlmostEqual(rec["peak_rate_mm_hr"], 50.8)
        self.assertAlmostEqual(rec["peak_rate_m_per_s"], 50.8 / 3.6e6)
        with open(anuga, newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["time_s", "rate_m_per_s"])
        t = [float(r[0]) for r in rows[1:]]
        r = [float(r_[1]) for r_ in rows[1:]]
        self.assertEqual(t[:3], [0.0, 3599.0, 3600.0])
        self.assertAlmostEqual(r[0], 25.4 / 3.6e6, places=12)
        # the ANUGA series integrates (m/s * s) to the storm depth in metres
        depth_m = sum((t[i + 1] - t[i]) * (r[i] + r[i + 1]) / 2 for i in range(len(t) - 1))
        self.assertAlmostEqual(depth_m, 0.0889, delta=0.0889 * 1e-4)
        # the two files describe the same storm
        self.assertAlmostEqual(R.integrate_mm(R.parse_rain(_slurp(rain))) / 1000.0, depth_m, places=6)
        readme = _slurp(rec["anuga_readme"])
        self.assertIn("anuga.Rate_operator", readme)
        self.assertIn("m/s", readme)
        self.assertIn("np.interp", readme)

    def test_export_needs_an_output(self):
        blocks, _ = R.read_hyetograph(self.csv)
        with self.assertRaises(R.RainError):
            R.export(blocks)

    def test_blocks_from_alternating_block_match_pointpf_depth(self):
        with open(os.path.join(FIX, "pfds_pds_english_fargo_nd.txt"), "rb") as fh:
            pf = A.parse(fh.read())
        for years, storm, step in ((100, 1440, 60), (500, 360, 15), (10, 720, 30)):
            rows = A.alternating_block(pf, years, storm, step)
            blocks = R.blocks_from_rows([(t, d) for t, d, _ in rows], "in")
            depth = pf["quantiles"][A.duration_index(dict((m, d) for d, m in A.DURATIONS)[storm])][A.freq_index(pf, years)]
            self.assertAlmostEqual(R.total_mm(blocks) / R.MM_PER_IN, depth, places=2)
            pts = R.series(blocks)
            self.assertAlmostEqual(R.integrate_mm(pts) / R.MM_PER_IN, depth, delta=depth * 0.001)


@unittest.skipUnless(os.environ.get("DAMIT_NETWORK_TESTS") == "1" and HAVE_GDAL, "set DAMIT_NETWORK_TESTS=1 (calls NOAA)")
class RealNoaa(unittest.TestCase):
    def test_dwr_2801_cell(self):
        from damit_core.lib import http
        tmp = tempfile.mkdtemp()
        try:
            p, rec = G.fetch_zip("mw", 100, "24-hr", "estimate", "pds", tmp,
                                 lambda u, d: http.download_file(u, d, timeout=120))
            self.assertGreater(rec["bytes"], 3000000)
            arr, gt, _ = G.read_clip(p, (-97.40, 46.97, -97.38, 46.99))
            v = G.value_at(arr, gt, -97.3911392204279, 46.9833779589273)
            self.assertAlmostEqual(v, 6.342, places=3)               # PFDS point query: 6.34 in
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
