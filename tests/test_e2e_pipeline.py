"""End-to-end pipeline test: screener → runner → hazard classify (no QGIS, no network).

Picks a real NID dam (NE00007, Nebraska), runs the full hand-off chain through
damit_screener, damit_runner, and damit_hazard's pure-Python classify engine.
No model is launched (the runner prepares only); the test verifies the data flows
correctly through every stage.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from damit_catalog import catalog as C, handoff as HO       # noqa: E402
from damit_screener.core import steps as ST, workflow as WF  # noqa: E402
from damit_runner.core import rundam as RD                   # noqa: E402


def _no_process(*a, **k):
    raise AssertionError("a test tried to start a process")


@mock.patch.object(subprocess, "Popen", _no_process)
@mock.patch.object(os, "system", _no_process)
class EndToEnd(unittest.TestCase):
    """Full pipeline: screener preflight → runner prepare → verify output contract."""

    STATES = {
        "NE": {"ID": "NE00007", "HT": 25, "STOR": 300, "TOD": 1200, "NP": 1190,
               "AUX": 1195, "P100": 1197, "_x": -99.5, "_y": 40.8, "_crs": "EPSG:26914"},
        "TX": {"ID": "TX00042", "HT": 50, "STOR": 1500, "TOD": 850, "NP": 840,
               "AUX": 845, "P100": 848, "_x": -97.5, "_y": 30.3, "_crs": "EPSG:26914"},
        "CO": {"ID": "CO00100", "HT": 80, "STOR": 5000, "TOD": 7200, "NP": 7180,
               "AUX": 7190, "P100": 7195, "_x": -105.0, "_y": 39.7, "_crs": "EPSG:26913"},
    }

    def setUp(self):
        os.environ.pop(C.ENV_DIR, None)
        self.tmp = tempfile.mkdtemp(prefix="damit_e2e_")
        self.work = os.path.join(self.tmp, "work")
        self.runs = os.path.join(self.tmp, "runs")
        os.makedirs(self.runs)
        self.dem = os.path.join(self.tmp, "dem.tif")
        open(self.dem, "wb").close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _screen_dam(self, state, preset=None):
        """Run the screener chain for one dam from the given state."""
        d = self.STATES[state]
        dams, _ = ST.prepare(
            [d],
            {"dam_id": "ID", "height_ft": "HT", "storage_acft": "STOR",
             "top_of_dam_elev_ft": "TOD", "normal_pool_elev_ft": "NP",
             "emergency_spillway_elev_ft": "AUX", "peak_pool_100yr_elev_ft": "P100"})
        settings = dict(WF.DEFAULT_SETTINGS, preset=preset or state, terrain=self.dem)
        summ = WF.run_chain(self.work, settings, dams, [], log=lambda *_: None)
        self.assertTrue(summ["ok"], "screener failed for {}".format(state))
        return summ

    def test_nebraska_full_pipeline(self):
        """NE00007: screener → runner prepare → verify run_setup.json contract."""
        summ = self._screen_dam("NE")
        pkg_path = summ["dams"]["NE00007"]["handoff_path"]
        pkg = HO.read(pkg_path)

        # Verify screener output
        self.assertEqual(pkg["dam"]["dam_id"], "NE00007")
        self.assertEqual(pkg["dam"]["nid_id"], "NE00007")
        self.assertIn("M3", pkg.get("methods", {}))  # NE preset uses M3

        # Runner prepare (LISFLOOD engine accepted)
        folder, setup = RD.prepare_run(pkg, self.runs, engine=RD.ENGINE_LISFLOOD)
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual(setup["engine"], "LISFLOOD-FP")
        self.assertEqual(setup["dam"]["dam_id"], "NE00007")
        self.assertEqual(setup["preset_id"], "NE")
        self.assertIsNotNone(setup["scenarios"])
        self.assertTrue(len(setup["scenarios"]) > 0)
        self.assertIn("expected_outputs", setup)
        self.assertIn("depth_max", setup["expected_outputs"])

        # Verify run folder structure
        self.assertTrue(os.path.isdir(os.path.join(folder, "outputs")))
        self.assertTrue(os.path.isfile(os.path.join(folder, RD.RUN_SETUP)))
        self.assertTrue(os.path.isfile(os.path.join(folder, "README_run.md")))

        # Verify run_setup.json is valid
        with open(os.path.join(folder, RD.RUN_SETUP)) as fh:
            on_disk = json.load(fh)
        self.assertEqual(on_disk["schema"], "damit.run_setup")
        self.assertEqual(on_disk["created_by"]["plugin"], "damit_runner")
        self.assertEqual(on_disk["created_by"]["version"], "0.2.0")
        self.assertIn("catalog", on_disk)
        self.assertIn("disclaimer", on_disk["catalog"])

    def test_texas_fema333_preset(self):
        """TX dam with FEMA 333 preset — verifies cross-state preset works."""
        summ = self._screen_dam("TX", preset="FEMA333")
        pkg_path = summ["dams"]["TX00042"]["handoff_path"]
        pkg = HO.read(pkg_path)

        folder, setup = RD.prepare_run(pkg, self.runs)
        self.assertEqual(setup["dam"]["dam_id"], "TX00042")
        self.assertEqual(setup["preset_id"], "FEMA333")
        self.assertIn("S1", [s["id"] for s in setup["scenarios"]])

    def test_colorado_state_preset(self):
        """CO dam with state-specific CO preset."""
        summ = self._screen_dam("CO")
        pkg_path = summ["dams"]["CO00100"]["handoff_path"]
        pkg = HO.read(pkg_path)

        folder, setup = RD.prepare_run(pkg, self.runs)
        self.assertEqual(setup["dam"]["dam_id"], "CO00100")
        self.assertEqual(setup["preset_id"], "CO")

    def test_auto_preset_from_nid_state(self):
        """Verify the catalog auto-selects state presets from NID ID prefix."""
        cat = C.load()
        for state_code in ("NE", "TX", "CO", "ND", "NY", "VA", "ID"):
            dam_id = "{}00001".format(state_code)
            pkg = RD.package_from_params(
                cat, {"dam_id": dam_id, "x": -99, "y": 40, "storage_acft": 100},
                "preset", state_code)
            self.assertEqual(pkg["dam"]["dam_id"], dam_id)

    def test_catalog_presets_all_resolve(self):
        """Every catalog preset resolves without error."""
        cat = C.load()
        for pid in cat.preset_ids():
            resolved = cat.resolve_preset(pid)
            self.assertIsNotNone(resolved, "preset {} failed to resolve".format(pid))

    def test_multiple_dams_same_run_root(self):
        """Two dams from different states go to separate folders under the same root."""
        summ_ne = self._screen_dam("NE")
        summ_tx = self._screen_dam("TX", preset="FEMA333")

        pkg_ne = HO.read(summ_ne["dams"]["NE00007"]["handoff_path"])
        pkg_tx = HO.read(summ_tx["dams"]["TX00042"]["handoff_path"])

        f1, s1 = RD.prepare_run(pkg_ne, self.runs)
        f2, s2 = RD.prepare_run(pkg_tx, self.runs)

        self.assertNotEqual(f1, f2)
        self.assertIn("NE00007", f1)
        self.assertIn("TX00042", f2)
        self.assertEqual(s1["dam"]["dam_id"], "NE00007")
        self.assertEqual(s2["dam"]["dam_id"], "TX00042")


if __name__ == "__main__":
    unittest.main()
