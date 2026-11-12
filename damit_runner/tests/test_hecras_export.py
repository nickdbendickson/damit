"""HEC-RAS export writes a project and does not run HEC-RAS or replace the flood rasters.
The chain's default is to skip the HEC-RAS run."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from damit_runner.core import chain
from damit_runner.core import hecras_export as HX


def _run(folder):
    os.makedirs(os.path.join(folder, "outputs"))
    with open(os.path.join(folder, "outputs", "Depth (Max).tif"), "wb") as f:
        f.write(b"not-a-real-tiff")
    with open(os.path.join(folder, "outputs", "breach_hydrograph.csv"), "w", encoding="utf-8") as f:
        f.write("time_hr,discharge_cfs\n0,0\n1,100\n2,0\n")
    report = {
        "dam_id": "ND00001",
        "dam": {"dam_id": "ND00001", "dam_height_ft": 20.0, "storage_top_acft": 500.0,
                "top_of_dam_ft": 1800.0},
        "hydrograph": {"method": "vtg1990", "failure_mode": "piping",
                       "breach_parameters": "Von Thun & Gillette",
                       "avg_breach_width_ft": 148.0, "bottom_width_ft": 130.0,
                       "side_slope_h": 0.5, "formation_time_hr": 0.5, "peak_cfs": 1000},
        "dam_xy": [500000.0, 5200000.0],
        "work_crs": "EPSG:26914",
        "inflow_point": {"xy": [500000.0, 5199900.0]},
        "settings": {"input_files": {"DEM": os.path.join(folder, "dem.tif")},
                     "cell_size_m": 10.0, "manning_n": 0.06},
        "crs_wkt": "EPSG:26914",
    }
    with open(os.path.join(folder, "dem.tif"), "wb") as f:
        f.write(b"dem")
    with open(os.path.join(folder, "run_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f)
    return report


class ChainDefault(unittest.TestCase):
    def test_missing_hec_mode_is_skip(self):
        self.assertEqual(chain.hec_mode({}), "skip")
        self.assertEqual(chain.hec_mode({"HEC_MODE": 0}), "run")
        self.assertEqual(chain.hec_mode({"HEC_MODE": 1}), "wait")
        cv, problems = chain.chain_values({})
        self.assertEqual(problems, [])
        self.assertEqual(cv["HEC_MODE"], 2)
        self.assertNotIn("hec_run", chain.plan_stages(cv, chain.hec_mode(cv)))
        self.assertNotIn("hec_build", chain.plan_stages(cv, chain.hec_mode(cv)))


class ExportDoesNotRun(unittest.TestCase):
    def test_stage_keeps_the_finished_opening_and_the_depth(self):
        tmp = tempfile.mkdtemp(prefix="damit_hex_")
        try:
            run = os.path.join(tmp, "run")
            os.makedirs(run)
            _run(run)
            depth = os.path.join(run, "outputs", "Depth (Max).tif")
            stamp = (os.path.getsize(depth), os.stat(depth).st_mtime_ns)
            stage = os.path.join(tmp, "stage")
            HX.prepare_stage(run, stage)
            self.assertEqual((os.path.getsize(depth), os.stat(depth).st_mtime_ns), stamp)
            self.assertFalse(os.path.isfile(os.path.join(run, "Depth (Max).tif")))
            with open(os.path.join(stage, "_breach_model", "run_report.json"), encoding="utf-8") as f:
                got = json.load(f)
            self.assertEqual(got["hydrograph"]["bottom_width_ft"], 130.0)
            self.assertTrue(os.path.isfile(os.path.join(stage, "Depth (Max).tif")))
            self.assertFalse(os.path.isfile(os.path.join(stage, "Velocity (Max).tif")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_export_does_not_call_the_solver(self):
        tmp = tempfile.mkdtemp(prefix="damit_hex2_")
        try:
            run = os.path.join(tmp, "run")
            os.makedirs(run)
            _run(run)
            called = {}

            def fake_build(stage, out_root=None, log=None, **k):
                called["stage"] = stage
                called["out"] = out_root
                os.makedirs(out_root, exist_ok=True)
                folder = os.path.join(out_root, "pkg")
                os.makedirs(folder)
                return {"folder": folder, "zip": folder + ".zip", "notes": ["not run"]}

            with mock.patch("damit_runner.core.hecras_package.build_package", fake_build):
                with mock.patch("damit_runner.core.hecras_engine.require",
                                side_effect=AssertionError("HEC-RAS was started")):
                    built = HX.export_package(run, out_folder=os.path.join(tmp, "out"),
                                             log=lambda *_: None)
            self.assertTrue(called["stage"])
            self.assertTrue(built["folder"].endswith("pkg"))
            self.assertFalse(os.path.isfile(os.path.join(run, "Depth (Max).tif")))
            self.assertTrue(os.path.isfile(os.path.join(run, "outputs", "Depth (Max).tif")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
