"""DamIT Runner (no QGIS): hand-off round trip, engine refusal, new run folders. Never starts a model."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from damit_runner.core import rundam as RD        # noqa: E402
from damit_screener.core import steps as ST       # noqa: E402
from damit_screener.core import workflow as WF    # noqa: E402
from damit_catalog import catalog as C            # noqa: E402
from damit_catalog import handoff as HO           # noqa: E402


def _no_process(*a, **k):
    raise AssertionError("a test tried to start a process: {!r}".format(a[:1]))


@mock.patch.object(subprocess, "Popen", _no_process)
@mock.patch.object(os, "system", _no_process)
class RoundTrip(unittest.TestCase):
    def setUp(self):
        os.environ.pop(C.ENV_DIR, None)
        self.tmp = tempfile.mkdtemp(prefix="damit_run_")
        self.work = os.path.join(self.tmp, "work")
        self.runs = os.path.join(self.tmp, "runs")
        os.makedirs(self.runs)
        dem = os.path.join(self.tmp, "dem.tif")
        open(dem, "wb").close()
        dams, _ = ST.prepare([{"ID": "NE00007", "HT": 25, "STOR": 300, "TOD": 1200, "NP": 1190, "AUX": 1195,
                               "P100": 1197, "_x": 1.0, "_y": 2.0, "_crs": "EPSG:26914"}],
                             {"dam_id": "ID", "height_ft": "HT", "storage_acft": "STOR", "top_of_dam_elev_ft": "TOD",
                              "normal_pool_elev_ft": "NP", "emergency_spillway_elev_ft": "AUX",
                              "peak_pool_100yr_elev_ft": "P100"})
        summ = WF.run_chain(self.work, dict(WF.DEFAULT_SETTINGS, preset="NE", terrain=dem), dams, [],
                            log=lambda *_: None)
        self.assertTrue(summ["ok"])
        self.pkg_path = summ["dams"]["NE00007"]["handoff_path"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_screener_package_accepted_by_runner(self):
        pkg = HO.read(self.pkg_path)
        folder, setup = RD.prepare_run(pkg, self.runs)
        self.assertTrue(folder.startswith(os.path.join(self.runs, "NE00007", "run_")))
        self.assertEqual(setup["status"], "prepared")
        self.assertFalse(setup["model_launched"])
        self.assertEqual(setup["engine"], "none")
        self.assertEqual(setup["preset_id"], "NE")
        self.assertEqual([s["id"] for s in setup["scenarios"]], ["S4"])
        self.assertEqual(setup["dam"]["scenario_pools"]["S4"]["pool_elev_ft"], 1197)
        self.assertEqual(setup["classification"]["algorithm"], "damit:classify")
        self.assertIn("M3", setup["catalog"]["citations"])
        self.assertEqual(setup["gaps"], [])
        self.assertTrue(setup["ready_to_run"])
        with open(os.path.join(folder, RD.RUN_SETUP)) as fh:
            self.assertEqual(json.load(fh)["schema"], "damit.run_setup")
        self.assertEqual(HO.read(folder)["dam"]["dam_id"], "NE00007")
        self.assertTrue(os.path.isdir(os.path.join(folder, "outputs")))
        self.assertEqual(os.listdir(os.path.join(folder, "outputs")), [])

    def test_never_reuses_a_run_folder(self):
        pkg = HO.read(self.pkg_path)
        f1, _ = RD.prepare_run(pkg, self.runs)
        marker = os.path.join(f1, "outputs", "keep.txt")
        open(marker, "w").close()
        import datetime
        same = datetime.datetime(2026, 11, 9, 12, 0, 0)
        f2, _ = RD.prepare_run(pkg, self.runs, now=same)
        f3, _ = RD.prepare_run(pkg, self.runs, now=same)
        self.assertEqual(len({f1, f2, f3}), 3)
        self.assertTrue(os.path.exists(marker))

    def test_unavailable_engines_refused(self):
        pkg = HO.read(self.pkg_path)
        # ANUGA (2) and HEC-RAS (3) are not yet ported
        for e in (2, 3):
            with self.assertRaises(RD.RunError) as cm:
                RD.prepare_run(pkg, self.runs, engine=e)
            self.assertIn("not yet available", str(cm.exception))
        # Invalid engine index
        with self.assertRaises(RD.RunError):
            RD.prepare_run(pkg, self.runs, engine=-1)

    def test_lisflood_engine_accepted(self):
        pkg = HO.read(self.pkg_path)
        # Engine 1 (LISFLOOD-FP) should be accepted for prepare (dry_run=True)
        folder, setup = RD.prepare_run(pkg, self.runs, engine=1)
        self.assertEqual(setup["engine"], "LISFLOOD-FP")

    def test_bad_packages_rejected(self):
        pkg = HO.read(self.pkg_path)
        for bad in ({"schema": "nddam.handoff"}, {"methods": {"M99": {}}}, {"dam": {"dam_id": ""}},
                    {"target": {"runner_algorithm": "ndbreach:rundam"}},
                    {"inputs": dict(pkg["inputs"], terrain="/nonexistent/dem.tif")}):
            p = dict(pkg, **bad)
            with self.assertRaises(RD.RunError):
                RD.prepare_run(p, self.runs)

    def test_equivalent_parameters(self):
        cat = C.load()
        pkg = RD.package_from_params(cat, {"dam_id": "ND00199", "x": 1, "y": 2, "storage_acft": 10}, "preset", "FEMA333")
        folder, setup = RD.prepare_run(pkg, self.runs, cat)
        self.assertEqual([s["id"] for s in setup["scenarios"]], ["S1"])
        self.assertEqual(setup["created_by"]["plugin"], "damit_runner")
        self.assertIn("terrain (DEM)", setup["gaps"])
        self.assertFalse(setup["ready_to_run"])

    def test_nid_ids_only(self):
        cat = C.load()
        pkg = HO.read(self.pkg_path)
        self.assertEqual(pkg["dam"]["nid_id"], "NE00007")
        for bad in ({"dam_id": "DWR-2801"}, {"dam_id": "DWR-2801", "nid_id": "ND00199"}, {"dam_id": "SAMPLE-4031"},
                    {"dam_id": "desk-x", "nid_id": "NEW"}, {"dam_id": "local-sample"}):
            p = dict(pkg, dam=dict(pkg["dam"], **dict({"nid_id": None, "is_new": False, "is_sample": False}, **bad)))
            with self.assertRaises(RD.RunError) as cm:
                RD.prepare_run(p, self.runs, cat)
            self.assertIn("NID", str(cm.exception))
        new = RD.package_from_params(cat, {"dam_id": "desk-new1", "is_new": True, "x": 1, "y": 2, "storage_acft": 10},
                                     "preset", "FEMA333")
        _, setup = RD.prepare_run(new, self.runs, cat)
        self.assertIsNone(setup["nid_id"])
        self.assertIn("new / proposed", setup["nid_warning"])
        sample = RD.package_from_params(cat, {"dam_id": "local-sample", "is_sample": True, "x": 1, "y": 2,
                                              "storage_acft": 10}, "preset", "FEMA333")
        _, setup = RD.prepare_run(sample, self.runs, cat)
        self.assertIn("desk sample", setup["nid_warning"])
        _, setup = RD.prepare_run(RD.package_from_params(cat, {"dam_id": "ND00199", "x": 1, "y": 2}, "preset", "FEMA333"),
                                  self.runs, cat)
        self.assertEqual((setup["nid_id"], setup["nid_warning"]), ("ND00199", None))


if __name__ == "__main__":
    unittest.main()
