"""heim runs 1.1.0: every run is kept, and `compare` puts a dam's runs side by side.

Why this exists: the DamSafety Runner writes every run of a dam to the same _breach_model/run_report.json, so
reading the dam again after switching from LISFLOOD-FP to a Boann engine replaced the first run, and the engine
comparisons the suite is mostly doing now could not be asked about. No model.
"""
import copy
import json
import os
import sqlite3
import unittest

from test_run_results import Base, DWR_REPORT, write_gpkg, gp_point


class CompareTest(Base):
    def rerun_2801(self, engine="Boann (gpu-subfv)", peak=30100.0, acres=12010.5, depth=11.2, s17=3.9):
        rep = copy.deepcopy(DWR_REPORT)
        rep["run_finished"] = "2026-11-21T09:00:00"
        rep["summary"].update({"final_model": engine, "peak_breach_cfs": peak, "flooded_acres": acres,
                               "max_depth_ft": depth})
        with open(os.path.join(self.dam, "_breach_model", "run_report.json"), "w") as f:
            json.dump(rep, f)
        gpkg = os.path.join(self.dam, "outputs", "Classification", "Habitable_Structures.gpkg")
        os.remove(gpkg)
        write_gpkg(gpkg,
                   {"Habitable_Structures": ("geom", [
                       (gp_point(623000.0, 5203000.0), {"Struct_ID": 17, "Address": "4512 Main St", "City": "Absaraka",
                                                        "Max_Depth_ft": s17, "Max_Vel_fps": 1.5,
                                                        "First_Arrival_hr": 2.5})])})

    def test_a_changed_report_is_kept_beside_the_earlier_one(self):
        self.add_all()
        self.rerun_2801()
        logs = []
        self.R.add([self.dam], log=logs.append)
        rows = self.q("SELECT final_model, current FROM runs WHERE dam_id='DWR-2801' ORDER BY run_finished")
        self.assertEqual(rows, [("LISFLOOD-FP", 0), ("Boann (gpu-subfv)", 1)])
        self.assertTrue(any("kept the earlier run" in m for m in logs))
        # the earlier run's rasters are the new run's files now
        self.assertEqual(self.q("SELECT COUNT(*) FROM rasters r JOIN runs u ON u.run_id=r.run_id "
                                "WHERE u.dam_id='DWR-2801' AND u.current=0"), [(0,)])

    def test_the_same_run_read_again_still_replaces(self):
        self.add_all()
        self.add_all()
        self.assertEqual(self.q("SELECT COUNT(*) FROM runs WHERE dam_id='DWR-2801'"), [(1,)])

    def test_compare_shows_numbers_and_differences(self):
        self.add_all()
        self.rerun_2801()
        self.R.add([self.dam], log=lambda m: None)
        db = self.R.connect()
        try:
            self.R.cmd_compare(db, "2801")
        finally:
            db.close()
        text = "\n".join(self.out)
        self.assertIn("LISFLOOD-FP", text)
        self.assertIn("Boann (gpu-subfv)", text)
        self.assertIn("28,671", text)
        self.assertIn("30,100 (+1,429, +5%)", text)
        self.assertIn("4512 Main St", text)
        self.assertIn("3.42 / 2.75", text)
        self.assertIn("3.9 / 2.5", text)
        self.assertIn("earlier run", text)
        self.assertIn("0.944 (same)", text)

    def test_compare_with_one_run_says_how_to_get_two(self):
        self.add_all()
        db = self.R.connect()
        try:
            with self.assertRaises(SystemExit) as cm:
                self.R.cmd_compare(db, "2801")
        finally:
            db.close()
        self.assertIn("only one run", str(cm.exception))

    def test_a_schema_1_database_is_upgraded(self):
        os.makedirs(os.path.dirname(self.db), exist_ok=True)
        db = sqlite3.connect(self.db)
        db.executescript(self.R.DDL.replace(", current INTEGER DEFAULT 1", ""))
        db.close()
        self.add_all()
        self.assertEqual(self.q("SELECT DISTINCT current FROM runs"), [(1,)])


if __name__ == "__main__":
    unittest.main()
