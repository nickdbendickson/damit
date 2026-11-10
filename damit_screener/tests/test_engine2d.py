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
        self.assertEqual(ST.engine2d({"dam_id": "X"}, {"engine2d": "lisflood"})["status"], ST.STATUS_FAIL)
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


if __name__ == "__main__":
    unittest.main()
