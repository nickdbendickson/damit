"""DamIT Screener 0.2.0 engine2d (no QGIS): the 2D screening flood runs in the chain, writes the screening rasters
into the dam folder, samples the receptors and gives a preliminary class. The finite-volume engine is replaced by
a stub: no flood model runs, and subprocess.Popen / os.system fail if anything tries to start a process."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import numpy  # noqa: F401
    from osgeo import gdal  # noqa: F401
    HAVE = True
except ImportError:                                        # pragma: no cover
    HAVE = False

from damit_screener.core import steps as ST                # noqa: E402
from damit_screener.core import workflow as WF             # noqa: E402
from damit_catalog import catalog as C                     # noqa: E402
from damit_catalog import handoff as HO                    # noqa: E402


def _no_process(*a, **k):
    raise AssertionError("a test tried to start a process: {!r}".format(a[:1]))


class Settings(unittest.TestCase):
    def test_timeout_from_env(self):
        self.assertEqual(ST.screening_timeout_s({}, {"DAMIT_SCREENING_TIMEOUT_S": "1000"}), 800.0)
        self.assertEqual(ST.screening_timeout_s({}, {}), 3600.0)
        self.assertEqual(ST.screening_timeout_s({"timeout_s": 120}, {"DAMIT_SCREENING_TIMEOUT_S": "1000"}), 120.0)
        self.assertEqual(WF.DEFAULT_SETTINGS["engine2d"], "builtin")
        self.assertEqual(WF.DEFAULT_SETTINGS["larger_clips"], 1)

    def test_off_and_gaps(self):
        self.assertEqual(ST.engine2d({"dam_id": "X"}, {"engine2d": "off"})["status"], ST.STATUS_NOT_RUN)
        self.assertEqual(ST.engine2d({"dam_id": "X"}, {"engine2d": "nope"})["status"], ST.STATUS_FAIL)
        self.assertEqual(ST.engine2d({"dam_id": "X"}, {"engine2d": "lisflood"})["status"], ST.STATUS_GAP)
        self.assertEqual(ST.engine2d({"dam_id": "X"}, {})["status"], ST.STATUS_GAP)


@unittest.skipUnless(HAVE, "numpy and GDAL needed")
@mock.patch.object(subprocess, "Popen", _no_process)
@mock.patch.object(os, "system", _no_process)
class Chain2D(unittest.TestCase):
    def setUp(self):
        os.environ.pop(C.ENV_DIR, None)
        from damit_runner.tests import synth
        from damit_runner.flood import screen as SC
        self.tmp = tempfile.mkdtemp(prefix="damit_e2d_")
        self.work = os.path.join(self.tmp, "work")
        self.dem = os.path.join(self.tmp, "dem.tif")
        self.site = synth.make_dem(self.dem)
        self.calls = []
        real = SC.simulate

        def sim(*a, **k):
            self.calls.append(a[0])
            k["engine_factory"] = synth.FakeFV
            return real(*a, **k)
        self.patch = mock.patch.object(SC, "simulate", sim)
        self.patch.start()
        dam_dir = WF.dam_folder(self.work, "ND00001")
        os.makedirs(dam_dir, exist_ok=True)
        with open(os.path.join(dam_dir, "dam_line.geojson"), "w") as fh:
            json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                       "geometry": {"type": "LineString", "coordinates": [list(c) for c in self.site["line"]]}}]}, fh)

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chain_runs_the_screening_flood(self):
        x, y = self.site["dam_xy"]
        top_ft = self.site["top_m"] / 0.3048
        h_ft = (self.site["top_m"] - self.site["floor_at_dam"]) / 0.3048
        dams, probs = ST.prepare([{"ID": "ND00001", "HT": h_ft, "STOR": 500, "TOD": top_ft, "_x": x, "_y": y,
                                   "_crs": "EPSG:26914"}],
                                 {"dam_id": "ID", "height_ft": "HT", "storage_acft": "STOR",
                                  "top_of_dam_elev_ft": "TOD"})
        recs = [{"id": "h1", "dam_id": "ND00001", "receptor_type": "structure", "structure_type": "home",
                 "habitable": True, "_x": x, "_y": y - 200.0, "_crs": "EPSG:26914"},
                {"id": "h2", "dam_id": "ND00001", "receptor_type": "structure", "structure_type": "home",
                 "habitable": True, "_x": x + 600.0, "_y": y - 200.0, "_crs": "EPSG:26914"}]
        s = dict(WF.DEFAULT_SETTINGS, preset="ND", terrain=self.dem)
        logs = []
        with mock.patch.dict(os.environ, {"DAMIT_SCREENING_TIMEOUT_S": "500"}):
            summ = WF.run_chain(self.work, s, dams, probs, recs, log=logs.append)
        self.assertTrue(summ["ok"], logs)
        r = summ["dams"]["ND00001"]
        e = r["engine2d"]
        self.assertIn(e["status"], (ST.STATUS_OK, ST.STATUS_GAP), e)
        self.assertEqual(self.calls[0]["timeout_s"], 400.0)            # 0.8 x DAMIT_SCREENING_TIMEOUT_S
        self.assertEqual(self.calls[0]["larger_clips"], 1)
        self.assertEqual(self.calls[0]["grid_m"], 20.0)
        self.assertEqual(e["receptors_sampled"], 2)
        self.assertEqual(e["model_dimension"], "2D")
        self.assertIn("3:1", e["inflow"]["toe_band"]["rule"])
        self.assertIn("top of dam", e["hydrograph"]["source"])
        folder = WF.dam_folder(self.work, "ND00001")
        for name in ("Screening Depth (Max).tif", "Screening Velocity (Max).tif", "Screening DV (Max).tif",
                     "Screening Arrival Time.tif"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        with open(os.path.join(folder, "receptors.json")) as fh:
            got = {x["id"]: x for x in json.load(fh)}
        self.assertGreater(got["h1"]["depth_ground_ft"], 3.0)
        self.assertEqual(got["h2"]["depth_ground_ft"], 0.0)
        if "m1_zone" in got["h1"]:                                    # DamIT Hazard's TM-11 charts are in the repo
            self.assertIn(got["h1"]["m1_zone"], ("high_danger", "judgment", "low_danger"))
        pkg = HO.read(r["handoff_path"])
        self.assertEqual(pkg["screening"]["status"], "computed_preliminary")
        self.assertIsNotNone(pkg["screening"].get("suggested_label"))
        with open(summ["report"]) as fh:
            self.assertIn("Screening flood (engine2d)", fh.read())
        # 0.3.2: the depth-velocity chart of the wet HABITABLE structures (Hazard's rule), a point sample, in the
        # dam folder; h2 is dry so only h1 is plotted
        dv = r["dv_chart"]
        self.assertIn(dv["status"], (ST.STATUS_OK, ST.STATUS_GAP), dv)
        import csv
        with open(os.path.join(folder, ST.DV_CHART_STEM + ".csv"), encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual([x["label"] for x in rows], ["h1"])
        self.assertEqual(rows[0]["source"], "Screener")
        self.assertIn("point sample", rows[0]["sampling"])
        self.assertEqual(dv["counts"]["total"], 1)
        try:
            import matplotlib.pyplot  # noqa: F401
            self.assertTrue(os.path.getsize(os.path.join(folder, ST.DV_CHART_STEM + ".png")) > 5000)
            self.assertEqual(dv["status"], ST.STATUS_OK)
        except Exception:                                           # no usable matplotlib: the CSV only, said in the step
            self.assertEqual(dv["status"], ST.STATUS_GAP)
            self.assertIn("matplotlib", dv["note"])

    def test_dv_chart_step_without_hazard_is_not_run_and_never_fails(self):
        from damit_screener.core import runner_bridge as RB
        with mock.patch.object(RB, "dvchart", return_value=None):
            st = ST.dv_chart({"dam_id": "ND00001"}, [{"id": "h", "receptor_type": "structure",
                                                         "structure_type": "home", "depth_ground_ft": 2.0,
                                                         "velocity_fps": 1.0}], self.tmp)
        self.assertEqual(st["status"], ST.STATUS_NOT_RUN)
        with mock.patch.object(RB, "dvchart", side_effect=RuntimeError("boom")):
            self.assertEqual(ST.dv_chart({"dam_id": "x"}, [], self.tmp)["status"], ST.STATUS_NOT_RUN)

    def test_engine2d_ok_with_a_damit_label_and_breach_direction_estimated(self):
        """DWR-2801: engine2d said GAP after a successful flood, labelled 'DamSafety Screening built-in 2D', and
        breach_direction was a GAP with no azimuth estimate."""
        x, y = self.site["dam_xy"]
        h_ft = (self.site["top_m"] - self.site["floor_at_dam"]) / 0.3048
        dams, probs = ST.prepare([{"ID": "ND00001", "HT": h_ft, "STOR": 500, "TOD": self.site["top_m"] / 0.3048,
                                   "_x": x, "_y": y, "_crs": "EPSG:26914"}],
                                 {"dam_id": "ID", "height_ft": "HT", "storage_acft": "STOR",
                                  "top_of_dam_elev_ft": "TOD"})
        s = dict(WF.DEFAULT_SETTINGS, preset="ND", terrain=self.dem, larger_clips=0)
        logs = []
        summ = WF.run_chain(self.work, s, dams, probs, [], log=logs.append)
        r = summ["dams"]["ND00001"]
        e = r["engine2d"]
        self.assertEqual(e["status"], ST.STATUS_OK, e)
        self.assertIn("DamIT Screener built-in", e["detail"])
        self.assertNotIn("DamSafety Screening built-in", json.dumps(e))
        self.assertTrue(e["engine"].startswith("DamIT Screener built-in"), e["engine"])
        self.assertFalse(e["engine_fallback"])
        b = r["breach_direction"]
        self.assertEqual(b["status"], ST.STATUS_OK, b)
        self.assertTrue(b["estimated"])
        self.assertEqual(b["method"], "dam line")
        self.assertLess(abs(b["azimuth_deg"] - 180.0), 20.0, b)      # the valley drains south
        t = r["terrain"]
        self.assertTrue(t["covers_dam"], t)
        self.assertEqual(t["crs"], "EPSG:26914")


@unittest.skipUnless(HAVE, "numpy and GDAL needed")
class BreachDirectionAndTerrainCrs(unittest.TestCase):
    def setUp(self):
        from damit_runner.tests import synth
        self.synth = synth
        self.tmp = tempfile.mkdtemp(prefix="damit_bdir_")
        self.dem = os.path.join(self.tmp, "dem.tif")
        self.site = synth.make_dem(self.dem)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def folder(self, line=True, reservoir=True):
        d = os.path.join(self.tmp, "dam_{}{}".format(int(line), int(reservoir)))
        os.makedirs(d, exist_ok=True)
        if line:
            with open(os.path.join(d, "dam_line.geojson"), "w") as fh:
                json.dump({"type": "Feature", "properties": {}, "geometry": {
                    "type": "LineString", "coordinates": [list(c) for c in self.site["line"]]}}, fh)
        if reservoir:
            with open(os.path.join(d, "reservoir_point.geojson"), "w") as fh:
                json.dump({"type": "Feature", "properties": {}, "geometry": {
                    "type": "Point", "coordinates": list(self.site["reservoir"])}}, fh)
        return d

    def dam(self, **kw):
        lon, lat = self.site["centre"]
        return dict({"dam_id": "ND00001", "x": lon, "y": lat, "crs": "EPSG:4326", "height_ft": 16.0}, **kw)

    def test_record_azimuth_wins(self):
        b = ST.breach_direction(self.dam(breach_azimuth_deg=370.0), self.dem, self.folder())
        self.assertEqual((b["status"], b["azimuth_deg"], b["estimated"]), (ST.STATUS_OK, 10.0, False))

    def test_estimates(self):
        b = ST.breach_direction(self.dam(), self.dem, self.folder())
        self.assertEqual(b["status"], ST.STATUS_OK, b)
        self.assertLess(abs(b["azimuth_deg"] - 180.0), 20.0, b)
        self.assertIn(b["confidence"], ("high", "medium", "low"))
        self.assertEqual(len(b["breach_lonlat"]), 2)
        b = ST.breach_direction(self.dam(), self.dem, self.folder(line=False))
        self.assertEqual((b["method"], b["confidence"]), ("reservoir to dam point", "low"))
        self.assertLess(abs(b["azimuth_deg"] - 180.0), 5.0, b)
        b = ST.breach_direction(self.dam(), self.dem, self.folder(line=False, reservoir=False))
        self.assertEqual(b["status"], ST.STATUS_OK, b)
        self.assertEqual(b["method"], "terrain trace")
        b = ST.breach_direction(self.dam(), None, self.folder(line=False, reservoir=False))
        self.assertEqual(b["status"], ST.STATUS_GAP)

    def test_terrain_coverage_in_the_dem_crs(self):
        """DWR-2801: an EPSG:5070 VRT with a lon / lat dam point said 'coverage not checked: CRS differs or
        unknown'."""
        from osgeo import gdal
        from damit_runner.flood import rasters as R
        lon, lat = self.site["centre"]
        x, y = R.transform_points([(lon, lat)], "EPSG:4326", "EPSG:5070")[0]
        import numpy as np
        tif = self.synth.write_tif(os.path.join(self.tmp, "t5070.tif"), np.full((50, 50), 300.0), x - 500.0,
                                   y + 500.0, 20.0, 5070)
        vrt = os.path.join(self.tmp, "3dep.vrt")
        gdal.BuildVRT(vrt, [tif])
        t = ST.terrain(self.dam(), vrt, {"crs": "EPSG:5070", "extent": (x - 500, y - 500, x + 500, y + 500)})
        self.assertEqual(t["status"], ST.STATUS_OK, t)
        self.assertTrue(t["covers_dam"])
        self.assertEqual(t["crs"], "EPSG:5070")
        self.assertNotIn("differs", t["detail"])
        far = self.dam(x=lon + 1.0)
        self.assertEqual(ST.terrain(far, vrt)["status"], ST.STATUS_GAP)
        t = ST.terrain({"dam_id": "X"}, vrt)
        self.assertIsNone(t["covers_dam"])


if __name__ == "__main__":
    unittest.main()
