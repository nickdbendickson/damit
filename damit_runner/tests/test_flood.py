"""DamIT Runner flood package and model run (no QGIS). The engines are stubbed: no LISFLOOD-FP, ANUGA, HEC-RAS,
Wine or built-in engine run, and subprocess.Popen / os.system fail if anything tries to start a process."""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import numpy as np                                    # noqa: F401
    from osgeo import gdal                                # noqa: F401
    HAVE = True
except ImportError:                                       # pragma: no cover - CI without GDAL
    HAVE = False

from damit_runner.core import rundam as RD                # noqa: E402


def _no_process(*a, **k):
    raise AssertionError("a test tried to start a process: {!r}".format(a[:1]))


@unittest.skipUnless(HAVE, "numpy and GDAL needed")
class ToeBand(unittest.TestCase):
    def test_band(self):
        from damit_runner.flood import geom as G
        (lo, hi), how, known = G.toe_band_for_dam(10.0, 2.0)
        self.assertEqual((lo, hi), (5.0, 30.0))
        self.assertTrue(known)
        (lo, hi), how, _ = G.toe_band_for_dam(10.0, None)        # 3:1 when the slope is missing
        self.assertEqual(hi, 40.0)
        self.assertIn("3:1", how)
        (lo, hi), _, _ = G.toe_band_for_dam(60.0, 3.0)           # 240 m -> the 150 m cap
        self.assertEqual(hi, 150.0)
        (lo, hi), _, _ = G.toe_band_for_dam(2.0, 2.0)            # 6 m -> at least 15 m
        self.assertEqual(hi, 15.0)


@unittest.skipUnless(HAVE, "numpy and GDAL needed")
@mock.patch.object(subprocess, "Popen", _no_process)
@mock.patch.object(os, "system", _no_process)
class ModelRun(unittest.TestCase):
    def setUp(self):
        from damit_runner.tests import synth
        from damit_runner.flood import lisflood as LF
        self.tmp = tempfile.mkdtemp(prefix="damit_flood_")
        self.dem = os.path.join(self.tmp, "dem.tif")
        self.site = synth.make_dem(self.dem)
        self.calls = []
        self.patch = mock.patch.object(LF, "run", synth.stub_lisflood(LF, self.calls))
        self.patch.start()
        self.h_ft = (self.site["top_m"] - self.site["floor_at_dam"]) / 0.3048

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def params(self, **kw):
        p = dict(dem=self.dem, dam_id="ND99999", height_ft=self.h_ft, storage_acft=500.0,
                 top_ft=self.site["top_m"] / 0.3048, dam_line_lonlat=self.site["line"],
                 reservoir_lonlat=self.site["reservoir"], lisflood_exe="builtin", max_runs=2)
        p.update(kw)
        return p

    def test_run_breach_writes_final_rasters(self):
        from damit_runner.flood import model as M
        out = os.path.join(self.tmp, "run")
        rec = M.run_breach(self.params(), out, log=lambda *_: None)
        self.assertTrue(self.calls)
        self.assertEqual(self.calls[0]["exe"], "builtin")
        for name in ("Depth (Max).tif", "Velocity (Max).tif", "Arrival Time.tif", "WSE (Max).tif", "hmax_ft.tif",
                     "Flood Polygons (Max Depth).geojson", "Flood Extent.geojson", "breach_hydrograph.csv"):
            self.assertTrue(os.path.isfile(os.path.join(out, "outputs", name)), name)
        from damit_runner.flood import breach as BR
        self.assertEqual(rec["hydrograph"]["method"], BR.METHOD_PIPING)
        self.assertIn("Froehlich", rec["hydrograph"]["label"])
        self.assertAlmostEqual(rec["hydrograph"]["starting_wse_ft"], self.site["top_m"] / 0.3048, 2)
        self.assertIn("top of dam", rec["hydrograph"]["rule"])
        self.assertEqual(rec["record_cell_m"], 10.0)
        # the inflow is on the downstream side, inside the toe band (5 m to H x (3 + 1), 3:1 default)
        ix, iy = rec["inflow"]["xy"]
        dx, dy = self.site["dam_xy"]
        dist = abs(iy - dy)
        self.assertLess(iy, dy)
        h_m = self.h_ft * 0.3048
        band = rec["inflow"]["toe_band"]
        self.assertEqual(band["inner_m"], 5.0)
        self.assertAlmostEqual(band["outer_m"], h_m * 4.0, 1)
        self.assertIn("3:1", band["rule"])
        self.assertGreaterEqual(dist, 5.0 - 2.0)
        self.assertLessEqual(dist, band["outer_m"] + 2.0)
        with open(os.path.join(out, "outputs", "units.json")) as fh:
            self.assertEqual(json.load(fh)["depth"], "ft")

    def test_hecras_refused_and_no_silent_builtin(self):
        from damit_runner.flood import model as M
        from damit_runner.flood import lisflood as LF
        with self.assertRaises(M.RunError):
            M.run_breach(self.params(tier=2), os.path.join(self.tmp, "r2"), log=lambda *_: None)
        with mock.patch.object(shutil, "which", lambda *_: None):
            with self.assertRaises(LF.ModelError):
                LF.resolve_exe("")
            with self.assertRaises(LF.ModelError):
                LF.resolve_exe("lisflood-not-here")
        self.assertEqual(LF.resolve_exe("builtin"), "builtin")

    def test_run_model_fills_the_dam_folder(self):
        from damit_catalog import catalog as C
        cat = C.load()
        lon, lat = self.site["centre"]
        pkg = RD.package_from_params(cat, {"dam_id": "ND00199", "x": lon, "y": lat, "crs": "EPSG:4326",
                                           "storage_acft": 500.0, "height_ft": self.h_ft,
                                           "top_of_dam_elev_ft": self.site["top_m"] / 0.3048},
                                     "preset", "ND", inputs={"terrain": self.dem})
        dams = os.path.join(self.tmp, "dams")
        dam_dir = os.path.join(dams, "ND00199")
        os.makedirs(dam_dir)
        with open(os.path.join(dam_dir, "dam_line.geojson"), "w") as fh:
            json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                       "geometry": {"type": "LineString", "coordinates": [list(c) for c in self.site["line"]]}}]}, fh)
        runs = os.path.join(self.tmp, "runs")
        folder, setup = RD.run_model(pkg, runs, {"LISFLOOD_EXE": "builtin", "MAX_RUNS": 2, "PMF_FT": 1200}, cat,
                                     dams, log=lambda *_: None)
        self.assertEqual(setup["status"], "finished")
        self.assertTrue(setup["model_launched"])
        self.assertEqual(setup["model_dimension"], "2D")
        self.assertEqual(setup["parameters"]["cell_m"], 10.0)
        self.assertEqual(setup["parameters"]["manning"], 0.06)
        self.assertEqual(setup["parameters"]["method"], "piping")
        self.assertTrue(any("PMF_FT" in n for n in setup["parameter_notes"]))
        for name in ("Depth (Max).tif", "Velocity (Max).tif", "hmax_ft.tif", "Flood Polygons (Max Depth).geojson"):
            self.assertTrue(os.path.isfile(os.path.join(dam_dir, name)), name)
        self.assertTrue(folder.startswith(os.path.join(runs, "ND00199", "run_")))
        with open(os.path.join(folder, RD.RUN_SETUP)) as fh:
            self.assertEqual(json.load(fh)["status"], "finished")
        with self.assertRaises(RD.RunError):
            RD.run_model(pkg, runs, {"ENGINE": RD.ENGINE_HECRAS}, cat, dams, log=lambda *_: None)

    def test_defaults_match_damsafety_runner(self):
        from damit_runner.flood import model as M
        want = {"CELL": 10.0, "MANNING": 0.06, "ARRIVAL_FT": 0.1, "EDGE_TOL_FT": 1.0, "LENGTH_MI": 4.0,
                "HALF_WIDTH_MI": 1.0, "STEP_MI": 3.0, "MAX_EXTENT_MI": 20.0, "MAX_RUNS": 6, "DURATION_MAX_HR": 96.0,
                "GRID_REFINE": True, "ANUGA_FINE": 100.0, "ANUGA_COARSE": 1000.0, "ANUGA_NEAR_MI": 1.0,
                "ANUGA_BUFFER": 500.0, "PIPE_FRACTION": 0.5, "PIPE_DIA_FT": 0.5, "KEEP_FILES": True,
                "PRODUCTS": True, "TIER": 0, "METHOD": 0}
        for k, v in want.items():
            self.assertEqual(RD.MODEL_PARAMS[k][1], v, k)
            key = RD.MODEL_PARAMS[k][0]
            if key in M.DEFAULTS and k not in ("METHOD", "TIER"):
                self.assertEqual(M.DEFAULTS[key], v, k)


@unittest.skipUnless(HAVE, "numpy and GDAL needed")
class Screening(unittest.TestCase):
    def setUp(self):
        from damit_runner.tests import synth
        self.synth = synth
        self.tmp = tempfile.mkdtemp(prefix="damit_scr2d_")
        self.dem = os.path.join(self.tmp, "dem.tif")
        self.site = synth.make_dem(self.dem)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_sim(self, factory, **kw):
        from damit_runner.flood import breach as BR, rasters as R, screen as SC
        wkt = R.model_wkt(self.dem, self.site["centre"])
        d = BR.DamData(dam_id="X", dam_height_ft=20.0, storage_top_acft=500.0, top_of_dam_ft=1099.0)
        hy = BR.make_hydrograph(d, BR.METHOD_PIPING)
        ix, iy = self.site["dam_xy"][0], self.site["dam_xy"][1] - 30.0
        p = dict({"dem": self.dem, "grid_m": 20.0, "timeout_s": 60.0}, **kw)
        return SC, wkt, SC.simulate(p, hy.t_s, hy.q_cms, {"inflow_xy": (ix, iy), "downstream": (0.0, -1.0),
                                                           "breach_width_m": 30.0, "vw_m3": 6e5}, wkt,
                                    lambda *_: None, None, engine_factory=factory)

    def test_simulate_and_receptors(self):
        SC, wkt, res = self.run_sim(self.synth.FakeFV)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["cell_m"], 20.0)
        g = res["grid"]
        ix, iy = self.site["dam_xy"][0], self.site["dam_xy"][1] - 30.0
        wet, dry = (ix, iy - 100.0), (ix + 400.0, iy - 100.0)
        h = SC.receptor_hydraulics(res, [wet, dry, (0.0, 0.0)])
        self.assertAlmostEqual(h[0]["depth_ground_ft"], round(1.0 / 0.3048, 2))
        self.assertAlmostEqual(h[0]["velocity_fps"], round(1.5 / 0.3048, 2))
        self.assertEqual(h[1], {"depth_ground_ft": 0.0, "velocity_fps": 0.0, "dv_ft2s": 0.0})
        self.assertIsNone(h[2])
        files = SC.write_rasters(self.tmp, res, wkt)
        for k in ("depth", "velocity", "dv", "arrival"):
            self.assertTrue(os.path.isfile(files[k]))
        self.assertTrue(g.dx == 20.0)

    def test_time_limit_keeps_partial_maxima(self):
        SC, wkt, res = self.run_sim(self.synth.TimeoutFV)
        self.assertEqual(res["status"], "partial")
        self.assertTrue(res["timed_out"])
        self.assertGreater(float(np.nanmax(res["depth"])), 0.5)
        self.assertTrue(any("partial" in n for n in res["notes"]))

    def test_first_clip_only(self):
        SC, wkt, res = self.run_sim(self.synth.FakeFV, larger_clips=0)
        self.assertEqual(res["larger_clips"], SC.LARGER_CLIPS[0])
        self.assertTrue(math.isclose(res["radius_m"], 1500.0))


if __name__ == "__main__":
    unittest.main()
