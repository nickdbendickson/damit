"""The screening DEM and the partial (time-limited) screening, 2026-11-20 (Absaraka, ND00199). Same tests as
DamIT Desk (damit-desk PR #2), plus DamIT Screener 0.3.7's partial flag on a chain that finishes OK.

The Report step's DEM went to the screener as TERRAIN but not into damit_settings.json, so every larger clip of the
screening flood downloaded USGS 3DEP afresh until the time limit; and a time-limited flood failed the whole chain with
"did not run" although it had written a preliminary class. Fake qgis_process from test_algorithms; nothing real runs.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import damit_desktop.qgis_run as qr  # noqa: E402
from damit_desktop import localdem  # noqa: E402
from test_algorithms import ANALYSIS, DAM, Base  # noqa: E402


class ScreeningDemTests(Base):
    def settings(self) -> dict:
        return json.loads((self.root / "work" / "damit_settings.json").read_text(encoding="utf-8"))

    def test_the_dams_dem_goes_into_the_settings_for_the_larger_clips(self):
        dem = self.root / "dems" / "cass_10m_3dep.vrt"
        dem.parent.mkdir()
        dem.write_text("<VRTDataset/>")
        qr.run_screening({**DAM, "demPath": str(dem)}, ANALYSIS, str(self.root / "work"), self.log)
        s = self.settings()
        self.assertEqual(Path(s["terrain"]), dem.resolve())
        self.assertEqual(s["larger_clips"], 2, "larger clips read the DEM, not a fresh 3DEP download")
        self.assertEqual(Path(s["local_dem"]), (self.root / "work" / "screen_dem"))
        self.assertEqual(sorted(x.name for x in Path(s["local_dem"]).iterdir()), ["cass_10m_3dep.vrt"])
        self.assertIn(f"--TERRAIN={dem.resolve()}", self.calls_text())
        self.assertTrue(any(line.startswith("Screening terrain: ") and "cass_10m_3dep.vrt" in line for line in self.lines))

    def test_damit_dem_counts_too(self):
        dem = self.root / "statewide.vrt"
        dem.write_text("<VRTDataset/>")
        with mock.patch.dict(os.environ, {"DAMIT_DEM": str(dem)}):
            qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertEqual(Path(self.settings()["terrain"]), dem.resolve())

    def test_the_dem_chosen_in_the_desk_is_used_when_the_field_is_empty(self):
        dem = self.root / "chosen.tif"
        dem.write_bytes(b"x")
        settings_file = self.root / "app-settings.json"
        localdem.write_dem_path(settings_file, str(dem))
        saved = qr.DESK_SETTINGS_FILE
        qr.DESK_SETTINGS_FILE = settings_file
        try:
            qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        finally:
            qr.DESK_SETTINGS_FILE = saved
        self.assertEqual(Path(self.settings()["terrain"]), dem.resolve())
        self.assertIn(f"--TERRAIN={dem.resolve()}", self.calls_text())

    def test_no_dem_says_the_screener_downloads(self):
        qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertNotIn("terrain", self.settings())
        self.assertTrue(any("downloads USGS 3DEP" in line for line in self.lines))


class PartialScreeningTests(Base):
    def test_a_time_limited_flood_is_a_partial_result_not_a_failure(self):
        with mock.patch.dict(os.environ, {"FAKE_CHAIN": "partial"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        self.assertTrue(result["partial"])
        self.assertTrue(result["timedOut"])
        self.assertEqual(result["screening"]["suggested_label"], "Medium")
        self.assertIn("PARTIAL SCREENING", result["warning"])
        self.assertIn("5,190.8 ac", result["warning"])
        text = "\n".join(self.lines)
        self.assertIn("preliminary Medium", text)
        self.assertIn("finished with a PARTIAL (preliminary) result", text)
        self.assertNotIn("The screening chain failed", text)

    def test_a_time_limited_flood_without_a_class_is_still_partial(self):
        # Absaraka 2026-11-20: no receptors were screened, so the package had no suggestion; the flood still ran.
        with mock.patch.dict(os.environ, {"FAKE_CHAIN": "partial-noclass"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        self.assertTrue(result["partial"])
        self.assertIsNone(result["screening"].get("suggested_label"))
        self.assertIn("no preliminary class", result["warning"])
        self.assertIn("5,190.8 ac", result["warning"])
        text = "\n".join(self.lines)
        self.assertIn("Also a gap in the suggest step", text)
        self.assertNotIn("The screening chain failed", text)

    def test_screener_0_3_7_partial_flag_on_a_chain_that_finishes_ok(self):
        # DamIT Screener 0.3.7 no longer fails the chain for a time-limited flood: it exits OK and marks the engine2d
        # step and the package gap partial=true. The app must still show the PARTIAL warning, not a plain "finished".
        with mock.patch.dict(os.environ, {"FAKE_CHAIN": "partial-ok"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        self.assertTrue(result["partial"])
        self.assertTrue(result["timedOut"])
        self.assertTrue(result["flood"]["timedOut"])
        self.assertEqual(result["screening"]["suggested_label"], "Medium")
        self.assertIn("PARTIAL SCREENING", result["warning"])
        text = "\n".join(self.lines)
        self.assertIn("The screener marked the flood PARTIAL (time limit) and finished the chain", text)
        self.assertNotIn("FAIL_ON_ERROR", text)
        self.assertIn("finished with a PARTIAL (preliminary) result", text)

    def test_a_finished_flood_is_not_partial(self):
        with mock.patch.dict(os.environ, {"FAKE_PACKAGE": "1"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["ok"], self.lines)
        self.assertNotIn("partial", result)
        self.assertIn("Screening chain finished.", self.lines)

    def test_a_real_failure_still_fails(self):
        with mock.patch.dict(os.environ, {"FAKE_CHAIN": "fail"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertFalse(result["ok"])
        self.assertNotIn("partial", result)
        self.assertIn("The screening chain failed. The flood model was not started.", self.lines)

    def test_a_package_from_an_earlier_run_is_not_this_runs_result(self):
        work = self.root / "work"
        old = qr.handoff_package(work, DAM["nid"])
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps({"screening": {"suggested_label": "High"}}))
        past = time.time() - 3600
        os.utime(old, (past, past))
        with mock.patch.dict(os.environ, {"FAKE_CHAIN": "nopkg-timeout"}):
            result = qr.run_screening(DAM, ANALYSIS, str(work), self.log)
        self.assertFalse(result["ok"])
        self.assertNotIn("High", "\n".join(self.lines))

    def test_the_time_limit_reaches_the_screener(self):
        with mock.patch.dict(os.environ, {"FAKE_CHAIN": "partial", "DAMIT_SCREENING_TIMEOUT_S": "900"}):
            result = qr.run_screening(DAM, ANALYSIS, str(self.root / "work"), self.log)
        self.assertTrue(result["partial"])
        self.assertTrue(any("The chain stops after 900 s" in line for line in self.lines))


if __name__ == "__main__":
    unittest.main()
