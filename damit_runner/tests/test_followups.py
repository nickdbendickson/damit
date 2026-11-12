"""DamIT Runner 0.3.0 follow-ups (review-only PR on top of #16): LISFLOOD-FP selection and fallback, the DamSafety
ANUGA mesh, the Screener's LISFLOOD-FP engine and fresh 3DEP clips, and the DWR-2801 real-engine fixes (the
OUTFLOW_EXTEND_PCT leak rule). Every engine and download is stubbed: no LISFLOOD-FP, ANUGA, HEC-RAS, Wine, built-in
engine or network; subprocess.Popen / os.system / urlopen fail if anything tries."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import numpy as np
    from osgeo import gdal                                # noqa: F401
    HAVE = True
except ImportError:                                       # pragma: no cover - CI without GDAL
    HAVE = False
try:
    import scipy.ndimage                                  # noqa: F401
    HAVE_SCIPY = True
except ImportError:                                       # pragma: no cover
    HAVE_SCIPY = False


def _no_process(*a, **k):
    raise AssertionError("a test tried to start a process: {!r}".format(a[:1]))


def _no_network(*a, **k):
    raise AssertionError("a test tried to download: {!r}".format(a[:1]))


def _exe(folder, name="lisflood"):
    p = os.path.join(folder, name)
    os.makedirs(folder, exist_ok=True)
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\nexit 1\n")
    os.chmod(p, 0o755)
    return p


# ------------------------------------------------------------------------------- item 3: find_exe --
@unittest.skipUnless(HAVE, "numpy and GDAL needed")
@mock.patch.object(subprocess, "Popen", _no_process)
class FindExe(unittest.TestCase):
    def setUp(self):
        from damit_runner.flood import lisflood as LF
        self.LF = LF
        self.tmp = tempfile.mkdtemp(prefix="damit_findexe_")
        self.p = [mock.patch.object(LF, "SYSTEM_GLOBS", ()), mock.patch.object(shutil, "which", lambda *a, **k: None)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in reversed(self.p):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def find(self, exe="", settings=None, environ=None):
        s = settings or {}
        return self.LF.find_exe(exe, settings=lambda k: s.get(k, ""), environ=environ or {}, home=self.tmp)

    def test_order(self):
        LF = self.LF
        a, b, c = _exe(os.path.join(self.tmp, "a")), _exe(os.path.join(self.tmp, "b")), _exe(os.path.join(self.tmp, "c"))
        self.assertEqual(self.find("builtin")["exe"], LF.BUILTIN)
        self.assertEqual(self.find(a)["how"], "LISFLOOD_EXE")
        with self.assertRaises(LF.ModelError) as e:                 # a named exe is never replaced
            self.find(os.path.join(self.tmp, "missing"))
        self.assertIn("Nothing was run", str(e.exception))
        self.assertEqual(self.find(settings={LF.SETTING_USE_BUILTIN: "true", LF.SETTING_DAMIT: a})["exe"], LF.BUILTIN)
        self.assertEqual(self.find(settings={LF.SETTING_DAMIT: a, LF.SETTING_NDBREACH: b})["exe"], a)
        r = self.find(settings={LF.SETTING_NDBREACH: b}, environ={LF.ENV_NDBREACH: c})
        self.assertEqual((r["exe"], r["how"]), (b, "provider setting " + LF.SETTING_NDBREACH))
        self.assertEqual(self.find(environ={LF.ENV_NDBREACH: c})["how"], LF.ENV_NDBREACH)
        with mock.patch.object(shutil, "which", lambda n, *x, **k: a if n == "lisflood" else None):
            self.assertEqual(self.find()["how"], "PATH (lisflood)")

    def test_nothing_found_falls_back_with_a_warning(self):
        r = self.find()
        self.assertEqual(r["exe"], self.LF.BUILTIN)
        self.assertEqual(r["warning"], self.LF.FALLBACK_WARNING)
        self.assertIn("BUILT-IN", r["warning"])

    def test_screener_choose_engine(self):
        from damit_runner.flood import screen as SC
        self.assertEqual(SC.choose_engine("builtin")[0], "builtin")
        kind, exe, how, warn = SC.choose_engine("lisflood", "", find_exe=lambda e: self.find(e))
        self.assertEqual(kind, "builtin")
        self.assertIn("BUILT-IN", warn)
        a = _exe(os.path.join(self.tmp, "a"))
        self.assertEqual(SC.choose_engine("lisflood", a, find_exe=lambda e: self.find(e))[:2], ("lisflood", a))
        with self.assertRaises(ValueError):
            SC.choose_engine("hecras")


# ----------------------------------------------------------------------- item 5: the DamSafety mesh --
@unittest.skipUnless(HAVE and HAVE_SCIPY, "numpy, GDAL and scipy needed")
@mock.patch.object(subprocess, "Popen", _no_process)
class AnugaMesh(unittest.TestCase):
    def grid(self):
        from damit_runner.flood.geom import Grid
        z = np.add.outer(np.linspace(110, 100, 120), np.zeros(100))
        return Grid(z, 600000.0, 5210000.0, 10.0)

    def flood(self, g, rows=slice(30, 90), cols=slice(40, 60), d=1.0):
        a = np.zeros(g.data.shape)
        a[rows, cols] = d
        return a

    def test_mesh_polygons_cover_the_flood_and_stay_in_the_dem(self):
        from damit_runner.flood import anuga_run as AR, mesh as M
        g = self.grid()
        depth = self.flood(g)
        inflow = g.xy(30, 50)
        outer, fine = AR.mesh_polygons(g, M.flooded_mask(depth), inflow, 100.0, 300.0)
        self.assertGreater(len(outer), 3)
        xmin, ymin, xmax, ymax = g.bounds
        self.assertTrue((outer[:, 0] >= xmin).all() and (outer[:, 0] <= xmax).all())
        self.assertTrue((outer[:, 1] >= ymin).all() and (outer[:, 1] <= ymax).all())
        # the flooded cells' box lies inside the outline's box (flood + buffer)
        fx0, fy1 = g.xy(30, 40)
        fx1, fy0 = g.xy(89, 59)
        self.assertLess(outer[:, 0].min(), fx0)
        self.assertGreater(outer[:, 0].max(), fx1)
        self.assertGreater(len(fine), 3)
        self.assertEqual(M.FLOODED_M, 0.05)
        self.assertFalse(M.flooded_mask(np.full((2, 2), 0.05)).any())
        il = M.inlet_line(inflow, (0.0, -1.0), 30.0)
        self.assertAlmostEqual(float(np.hypot(*(il[1] - il[0]))), 30.0)

    def test_run_two_passes_when_the_flood_reaches_the_mesh_edge(self):
        from damit_runner.flood import anuga_run as AR, lisflood as LF
        g = self.grid()
        tmp = tempfile.mkdtemp(prefix="damit_anuga_")
        self.addCleanup(shutil.rmtree, tmp, True)
        jobs = []

        def fake_launch(cmd, workdir, logp, wall, env, cancel, label):
            py, worker, job, out = cmd
            with np.load(job, allow_pickle=False) as j:
                jobs.append({"boundary": np.array(j["boundary"]), "inlet": np.array(j["inlet"]),
                             "edge_bc": str(j["edge_bc"]), "threads": int(j["threads"])})
            d = self.flood(g, rows=slice(30, 120)) if len(jobs) == 1 else self.flood(g, rows=slice(30, 100))
            np.savez(out, depth=d, velocity=d, arrival_hr=np.where(d > 0, 1.0, np.nan), wse=g.data + d,
                     stats=json.dumps({"triangles": 1000 * len(jobs)}))
            return 0

        hy = mock.Mock(t_s=np.array([0.0, 3600.0]), q_cms=np.array([100.0, 0.0]))
        p = {"manning": 0.06, "fine_m2": 100.0, "coarse_m2": 1000.0, "near_m": 1609.0, "buffer_m": 100.0,
             "sim_time_s": 7200.0, "arrival_m": 0.03, "threads": 1, "python": sys.executable, "wall_s": 60.0,
             "edge_tol_m": 0.3048}
        with mock.patch.object(LF, "launch", fake_launch):
            res = AR.run(tmp, g, self.flood(g), g.xy(30, 50), (0.0, -1.0), 5.0, hy, p, log=lambda *_: None)
        self.assertEqual(len(jobs), 2)                                  # second, wider pass
        self.assertEqual([r["buffer_m"] for r in res["mesh"]["runs"]], [100.0, 200.0])
        self.assertEqual(res["mesh"]["inlet_width_m"], 30.0)            # max(3 cells, breach width)
        self.assertEqual(jobs[0]["edge_bc"], "outflow")
        self.assertEqual(jobs[0]["threads"], 1)
        for f in ("mesh_boundary.csv", "mesh_fine_area.csv", "anuga_job.npz"):
            self.assertTrue(os.path.isfile(os.path.join(tmp, f)), f)
        self.assertIn("DamSafety Runner default", res["mesh"]["mesher"])

    def test_no_scipy_is_an_error_not_a_simpler_mesh(self):
        from damit_runner.flood import anuga_run as AR
        with mock.patch.object(AR, "have_scipy", lambda: False):
            with self.assertRaises(AR.AnugaError):
                AR.run(tempfile.gettempdir(), self.grid(), None, (0, 0), (0, -1), 10, None,
                       {"python": sys.executable})


# ----------------------------------------------- item 2: Screener LISFLOOD-FP and fresh 3DEP larger clips --
@unittest.skipUnless(HAVE, "numpy and GDAL needed")
@mock.patch.object(subprocess, "Popen", _no_process)
@mock.patch.object(urllib.request, "urlopen", _no_network)
class ScreenerEngines(unittest.TestCase):
    def setUp(self):
        from damit_runner.tests import synth
        self.synth = synth
        self.tmp = tempfile.mkdtemp(prefix="damit_scrf_")
        self.dem = os.path.join(self.tmp, "dem.tif")
        self.site = synth.make_dem(self.dem)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sim(self, factory=None, fetch=None, **kw):
        from damit_runner.flood import breach as BR, rasters as R, screen as SC
        wkt = R.model_wkt(self.dem, self.site["centre"])
        d = BR.DamData(dam_id="X", dam_height_ft=20.0, storage_top_acft=500.0, top_of_dam_ft=1099.0)
        hy = BR.make_hydrograph(d, BR.METHOD_PIPING)
        ix, iy = self.site["dam_xy"][0], self.site["dam_xy"][1] - 30.0
        p = dict({"dem": self.dem, "grid_m": 20.0, "timeout_s": 60.0, "workdir": self.tmp}, **kw)
        return SC, SC.simulate(p, hy.t_s, hy.q_cms, {"inflow_xy": (ix, iy), "downstream": (0.0, -1.0),
                                                     "breach_width_m": 30.0, "vw_m3": 6e5}, wkt,
                               lambda *_: None, None, engine_factory=factory, fetch_terrain=fetch)

    def test_lisflood_engine_through_simulate(self):
        from damit_runner.flood import lisflood as LF
        exe = _exe(os.path.join(self.tmp, "bin"))
        calls = []

        def fake_run(workdir, par, e, max_wall_s=0.0, threads=0, cancel=None, log=None):
            calls.append({"exe": e, "threads": threads})
            a = LF.read_asc(os.path.join(workdir, "run.dem.asc"))
            h = np.zeros(a.shape)
            h[a.shape[0] // 3: a.shape[0] // 3 + 10, a.shape[1] // 2 - 3: a.shape[1] // 2 + 3] = 0.7
            os.makedirs(os.path.join(workdir, "results"), exist_ok=True)
            for ext, arr in ((".max", h), (".maxVc", h), (".inittm", np.where(h > 0, 1.0, -9999))):
                LF.write_asc(os.path.join(workdir, "results", "run" + ext), arr, 0, 0, 20.0)
            return {"engine": "stub", "wall_s": 0.1}
        with mock.patch.object(LF, "run", fake_run):
            SC, res = self.sim(engine="lisflood", lisflood_exe=exe, larger_clips=0)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(calls and calls[0]["exe"] == exe and calls[0]["threads"] == 1)
        self.assertIn("LISFLOOD-FP ACC", res["engine"])
        self.assertFalse(res["engine_fallback"])
        self.assertGreater(float(np.nanmax(res["depth"])), 0.5)

    def test_larger_clips_are_fresh_3dep_downloads(self):
        got = []

        def fetch(bounds, wkt, cell, folder, radius_m, log, deadline):
            got.append({"radius": radius_m, "folder": folder, "cell": cell})
            return {"path": self.dem, "z_units": "m", "source": "USGS 3DEP (stub)", "tiles": 1,
                    "folder": os.path.join(folder, "terrain_3dep", "r{:.0f}m".format(radius_m))}
        SC, res = self.sim(self.synth.EdgeFV, fetch, radius_max_m=3000.0)
        self.assertEqual([g["radius"] for g in got], [3000.0])
        self.assertEqual(got[0]["folder"], os.path.join(self.tmp, "screen_inputs"))
        self.assertEqual(res["terrain"]["source"], "USGS 3DEP (stub)")
        self.assertEqual([t["radius_m"] for t in res["terrains"]], [1500.0, 3000.0])
        self.assertTrue(any("fresh 3DEP download" in n for n in res["notes"]))

    def test_failed_download_falls_back_to_the_run_dem_with_a_note(self):
        def fetch(*a, **k):
            raise IOError("service down")
        SC, res = self.sim(self.synth.EdgeFV, fetch, radius_max_m=3000.0)
        self.assertTrue(res["terrains"][-1].get("fallback"))
        self.assertTrue(any("3DEP download for the 3000 m clip failed" in n for n in res["notes"]))

    def test_corridor_widening_does_not_end_the_clip_growth(self):
        """DWR-2801: 0.2.0 said 'no terrain beyond the clip' after a corridor widening on the same 1,500 m clip."""
        from damit_runner.flood import screen as SC
        seq = iter([(True, True), (True, False), (False, False), (False, False)])
        with mock.patch.object(SC.DM, "touches_wall", lambda *a, **k: next(seq)):
            _, res = self.sim(self.synth.FakeFV, larger_clips=2, radius_max_m=3000.0)
        self.assertEqual(res["radius_m"], 3000.0)
        self.assertFalse(any("no terrain beyond" in n for n in res["notes"]))

    def test_fetch_clip_requests_and_new_folders(self):
        from damit_runner.flood import rasters as R, terrain3dep as T3
        wkt = R.model_wkt(self.dem, self.site["centre"])
        x, y = self.site["dam_xy"]
        b = (x - 600.0, y - 600.0, x + 600.0, y + 600.0)
        calls = []
        r = T3.fetch_clip(b, wkt, 20.0, os.path.join(self.tmp, "screen_inputs"), 600.0,
                          opener=self.synth.fake_3dep_opener(calls), sleep=lambda *_: None)
        self.assertTrue(os.path.isfile(r["path"]) and r["path"].endswith("3dep.vrt"))
        self.assertEqual(r["folder"], os.path.join(self.tmp, "screen_inputs", "terrain_3dep", "r600m"))
        q = calls[0]["q"]
        self.assertEqual(q["imageSR"], "5070")
        self.assertEqual(q.get("pixelType"), "F32")
        g = R.read_window(r["path"], b, 20.0, wkt, "m")
        self.assertTrue(np.isfinite(g.data).all())
        r2 = T3.fetch_clip(b, wkt, 20.0, os.path.join(self.tmp, "screen_inputs"), 600.0,
                           opener=self.synth.fake_3dep_opener([]), sleep=lambda *_: None)
        self.assertTrue(r2["folder"].endswith("r600m_1"))                 # never into an existing folder
        with self.assertRaises(Exception):
            T3.fetch_clip(b, wkt, 20.0, os.path.join(self.tmp, "x"), 600.0,
                          opener=self.synth.fake_3dep_opener([], body=b"<html>busy</html>"), sleep=lambda *_: None)


# ------------------------------------------------- DWR-2801 fix 5: OUTFLOW_EXTEND_PCT, as the DamSafety Runner --
def _mass(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("Time Tstep MinTstep NumTsteps Area Vol Qin Hds Qout Qerror Verror\n")
        for t, qin, qout in rows:
            fh.write("{} 1 1 1 0 0 {} 0 {} 0 0\n".format(t, qin, qout))


@unittest.skipUnless(HAVE, "numpy and GDAL needed")
@mock.patch.object(subprocess, "Popen", _no_process)
class OutflowExtend(unittest.TestCase):
    def setUp(self):
        from damit_runner.tests import synth
        self.tmp = tempfile.mkdtemp(prefix="damit_leak_")
        self.dem = os.path.join(self.tmp, "dem.tif")
        self.site = synth.make_dem(self.dem)
        self.h_ft = (self.site["top_m"] - self.site["floor_at_dam"]) / 0.3048

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stub(self, qout):
        from damit_runner.flood import lisflood as LF
        calls = []

        def fake_run(workdir, par, exe, max_wall_s=0.0, threads=0, cancel=None, log=None):
            calls.append(workdir)
            a = LF.read_asc(os.path.join(workdir, "run.dem.asc"))
            ny, nx = a.shape
            h = np.zeros(a.shape)
            h[ny // 3:, nx // 2 - 5:nx // 2 + 5] = 0.1          # shallow (0.33 ft) but wet down to the S edge
            res = os.path.join(workdir, "results")
            os.makedirs(res, exist_ok=True)
            for ext, arr in ((".max", h), (".maxVc", h), (".inittm", np.where(h > 0, 1.0, -9999))):
                LF.write_asc(os.path.join(res, "run" + ext), arr, 0, 0, 10.0)
            _mass(os.path.join(res, "run.mass"), [(0, 100.0, 0.0), (3600, 100.0, qout), (7200, 0.0, qout)])
            return {"engine": "stub", "wall_s": 0.1, "wall_limit_s": 60.0, "unpatched": False}
        return LF, calls, fake_run

    def run_it(self, qout, **kw):
        from damit_runner.flood import model as M
        LF, calls, fake = self.stub(qout)
        p = dict(dem=self.dem, dam_id="ND99999", height_ft=self.h_ft, storage_acft=500.0,
                 top_ft=self.site["top_m"] / 0.3048, dam_line_lonlat=self.site["line"],
                 reservoir_lonlat=self.site["reservoir"], lisflood_exe="builtin", max_runs=2, duration_hr=4.0,
                 length_mi=0.5, half_width_mi=0.25, step_mi=0.25)        # a domain well inside the DEM
        p.update(kw)
        with mock.patch.object(LF, "run", fake):
            rec = M.run_breach(p, os.path.join(self.tmp, "run{}".format(qout)), log=lambda *_: None)
        return rec, calls

    def passes(self, rec):
        return (rec.get("growth") or rec.get("lisflood") or {}).get("passes") or rec.get("passes")

    def test_mass_outflow(self):
        from damit_runner.flood import lisflood as LF
        d = os.path.join(self.tmp, "w")
        _mass(os.path.join(d, "results", "run.mass"), [(0, 100.0, 0.0), (3600, 100.0, 50.0), (7200, 0.0, 50.0)])
        o = LF.boundary_outflow(d)
        self.assertAlmostEqual(o["outflow_pct"], round(100.0 * 270000.0 / 540000.0, 2))
        self.assertIsNone(LF.boundary_outflow(os.path.join(self.tmp, "none")))

    def test_leaking_edge_moves_out_under_the_depth_tolerance(self):
        rec, calls = self.run_it(qout=60.0)                       # ~67% of the volume leaves
        self.assertEqual(len(calls), 2)
        text = json.dumps(rec)
        self.assertIn('"over_outflow": ["S"]', text)
        self.assertTrue(any("left the model through its edges" in w for w in rec["warnings"]))
        self.assertTrue(any("clock extension is not counted" in w for w in rec["warnings"]))

    def test_small_outflow_does_not_extend(self):
        rec, calls = self.run_it(qout=1.0)                        # ~1%: under OUTFLOW_EXTEND_PCT 5
        self.assertEqual(len(calls), 1)
        self.assertIn('"over_outflow": []', json.dumps(rec))
        # 0.3.3: no growth, but the wet S edge with ~1 % gone is said at the end of the loop (it used to be silent)
        w = [x for x in rec["warnings"] if "left the model" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("S 0.33 ft", w[0])
        self.assertIn("The domain was not grown further", w[0])

    def test_the_end_of_run_warnings_are_in_the_log(self):
        from damit_runner.flood import model as M
        LF, calls, fake = self.stub(1.0)
        lines = []
        p = dict(dem=self.dem, dam_id="ND99999", height_ft=self.h_ft, storage_acft=500.0,
                 top_ft=self.site["top_m"] / 0.3048, dam_line_lonlat=self.site["line"],
                 reservoir_lonlat=self.site["reservoir"], lisflood_exe="builtin", max_runs=2, duration_hr=4.0,
                 length_mi=0.5, half_width_mi=0.25, step_mi=0.25)
        with mock.patch.object(LF, "run", fake):
            rec = M.run_breach(p, os.path.join(self.tmp, "runlog"), log=lines.append)
        for w in rec["warnings"]:
            self.assertIn("Warning: " + w, lines)
        self.assertTrue([l for l in lines if l.startswith("Warning: ") and "left the model" in l])

    def test_outflow_extend_pct_zero_turns_it_off(self):
        rec, calls = self.run_it(qout=60.0, outflow_extend_pct=0.0)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
