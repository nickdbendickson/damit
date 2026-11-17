"""damit_pmp:lisfloodrain pieces (lisfloodrain.py, launch.run_lisflood): settings, the .rain / .bci / .par / .gauge files,
the runner reuse (every shared .par line pinned to lisflood.write_inputs), the domain, the launcher with a stand-in
executable and the result readers. Needs numpy, scipy and GDAL (skips otherwise); no QGIS, no real LISFLOOD-FP."""
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

try:
    import numpy as np
    import scipy  # noqa: F401
    from osgeo import gdal
    gdal.UseExceptions()
    HAVE = True
except ImportError:                                            # pragma: no cover
    HAVE = False

if HAVE:
    from damit_pmp import anugarain as AR
    from damit_pmp import launch
    from damit_pmp import lisfloodrain as LR
    from damit_pmp.runner_shared import lisflood as L
    from damit_pmp.runner_shared.grid import NODATA, Grid
    from damit_pmp.tests.test_anuga_rain import circle, make_dem

REAL_EXE = os.environ.get("DAMIT_PMP_LISFLOOD", "")


def stand_in_exe(folder, depth=0.12, qout=0.5):
    """An executable that reads rain.par like LISFLOOD-FP would and writes the result files the readers need."""
    path = os.path.join(folder, "fake_lisflood")
    with open(path, "w") as fh:
        fh.write(textwrap.dedent("""\
            #!{py}
            import os, sys
            par = dict((l.split() + [""])[:2] for l in open(sys.argv[2]) if l.strip() and not l.startswith("#"))
            print("args", sys.argv[1:], "OMP", os.environ.get("OMP_NUM_THREADS"))
            lines = open(par["DEMfile"].strip()).read().splitlines()
            os.makedirs("results", exist_ok=True)
            out = lines[:6] + [" ".join("0.000" if v == "-9999.000" else "{depth}" for v in l.split()) for l in lines[6:]]
            open("results/rain.max", "w").write("\\n".join(out) + "\\n")
            open("results/rain.mass", "w").write("Time Tstep MinTstep NumTsteps Area Vol Qin Hds Qout Qerror Verror Rain\\n"
                "10 10 10 1 0 100 0 0 0 0 0 100\\n7200 10 10 720 0 900 0 0 {qout} 0 0 1000\\n")
            open("results/rain.discharge", "w").write("Discharge output\\n\\nTime; discharge 1 to 1\\n10 0.0\\n300 0.2\\n600 -0.7\\n900 0.1\\n")
            """).format(py=sys.executable, depth=depth, qout=qout))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Settings(unittest.TestCase):
    def test_defaults_are_the_runners(self):
        s = LR.check_settings({})
        self.assertEqual((s["solver"], s["manning_n"], s["initial_tstep_s"], s["cell_m"]), ("acceleration", 0.06, 10.0, 10.0))
        self.assertEqual(s["theta"], 1.0)
        self.assertIsNone(s["cfl"])

    def test_solver_choice_is_the_runners(self):
        self.assertEqual(LR.check_settings({"solver": "FV2"})["solver"], "fv2")
        self.assertEqual(LR.check_settings({"solver": "MWDG2"})["solver"], "mwdg2")
        for bad in ("FV1", "DG2", "wat"):
            with self.assertRaises(AR.JobError) as cm:
                LR.check_settings({"solver": bad})
            self.assertIn("cannot be used", str(cm.exception))
        self.assertEqual(LR.SOLVER_CHOICES, ("ACC", "FV2", "MWDG2"))
        self.assertEqual(tuple(LR.L.solver_from_text(s) for s in LR.SOLVER_CHOICES), L.MAIN_SOLVERS)

    def test_bad_values_name_the_key(self):
        for kw, word in (({"cell_m": 0.1}, "cell_m"), ({"manning_n": 0}, "manning_n"), ({"massint_s": 0}, "massint_s"),
                         ({"theta": 1.5}, "theta"), ({"cfl": 0}, "cfl"), ({"closed_edges": ["Q"]}, "edge")):
            with self.assertRaises(AR.JobError) as cm:
                LR.check_settings(kw)
            self.assertIn(word, str(cm.exception))

    def test_cuda_note_is_there(self):
        self.assertIn("CUDA", LR.CUDA_NOTE)
        self.assertIn("silently", LR.CUDA_NOTE)


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Executable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_explicit_path_and_errors(self):
        exe = stand_in_exe(self.tmp)
        self.assertEqual(LR.find_exe(exe), exe)
        with self.assertRaises(AR.JobError):
            LR.find_exe(os.path.join(self.tmp, "nope"))
        plain = os.path.join(self.tmp, "plain")
        open(plain, "w").close()
        with self.assertRaises(AR.JobError) as cm:
            LR.find_exe(plain)
        self.assertIn("not executable", str(cm.exception))

    def test_the_builtin_numpy_engine_is_never_offered(self):
        with self.assertRaises(AR.JobError) as cm:
            LR.find_exe("builtin")
        self.assertIn("not LISFLOOD-FP", str(cm.exception))

    def test_search_uses_the_runners_environment_variable(self):
        exe = stand_in_exe(self.tmp)
        old = os.environ.get("DAMIT_LISFLOOD")
        os.environ["DAMIT_LISFLOOD"] = exe
        try:
            self.assertEqual(LR.find_exe(""), exe)
        finally:
            if old is None:
                os.environ.pop("DAMIT_LISFLOOD")
            else:
                os.environ["DAMIT_LISFLOOD"] = old


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Inputs(unittest.TestCase):
    def test_rain_file_is_mm_per_hr_with_the_same_volume(self):
        t = np.array([0, 1799, 1800, 3599, 3600, 7200.0])
        r = np.array([1e-6, 1e-6, 2e-6, 2e-6, 0.0, 0.0])
        txt = LR.rain_text(t, r, "test").splitlines()
        self.assertEqual(txt[0], "# test")
        self.assertEqual(txt[1], "6 seconds")
        self.assertEqual(txt[2].split(), ["3.600000", "0.000"])
        rows = np.array([[float(v) for v in ln.split()] for ln in txt[2:]])
        vol = np.trapz(rows[:, 0] / 3.6e6, rows[:, 1]) if hasattr(np, "trapz") else np.trapezoid(rows[:, 0] / 3.6e6, rows[:, 1])
        self.assertAlmostEqual(vol, AR.rain_depth_m(t, r), places=9)
        self.assertAlmostEqual(LR.depth_mm(t, r), AR.rain_depth_m(t, r) * 1000.0)

    def test_series_that_ends_wet_gets_a_zero_row(self):
        txt = LR.rain_text([0, 100.0], [1e-6, 1e-6]).splitlines()
        self.assertEqual(txt[1], "3 seconds")
        self.assertEqual(txt[-1].split(), ["0.000000", "101.000"])
        with self.assertRaises(AR.JobError):
            LR.rain_text([0.0], [1e-6])

    def test_repeated_times_are_dropped(self):
        txt = LR.rain_text([0, 10, 10, 20.0], [1e-6, 1e-6, 2e-6, 0.0]).splitlines()
        self.assertEqual(txt[1], "3 seconds")

    def test_par_lines_are_the_runners_keywords(self):
        shared, only_rain, only_runner = LR.runner_inputs_match()
        self.assertEqual(only_rain, {"rainfall rain.rain"})
        self.assertEqual(only_runner, {"bdyfile rain.bdy", "hazard", "inittm_depth 0.0305"})
        for k in ("acceleration", "depthoff", "elevoff", "fpfric 0.0600", "dirroot results", "resroot rain"):
            self.assertIn(k, shared)

    def test_fv2_and_theta_keywords(self):
        st = LR.check_settings({"solver": "FV2"})
        lines = LR.par_lines(st, 3600.0)
        self.assertIn("fv2", lines)
        self.assertIn("limitslopes", lines)
        self.assertNotIn("acceleration", lines)
        st = LR.check_settings({"theta": 0.7, "cfl": 0.5})
        lines = LR.par_lines(st, 3600.0)
        self.assertIn("theta 0.700", lines)
        self.assertIn("cfl 0.500", lines)
        self.assertFalse(any(ln.startswith(("theta", "cfl")) for ln in LR.par_lines(LR.check_settings({}), 3600.0)))

    def test_gauge_direction_follows_the_flow(self):
        g = LR.gauge_from_ab((0.0, 100.0), (0.0, -100.0), downstream_xy=(-500.0, 0.0))      # a N-S line east of the start
        self.assertEqual((g["direction"], g["width_m"], g["xy"]), ("E", 200.0, (0.0, 0.0)))
        g = LR.gauge_from_ab((0.0, 100.0), (0.0, -100.0), downstream_xy=(500.0, 0.0))
        self.assertEqual(g["direction"], "W")
        g = LR.gauge_from_ab((-100.0, 0.0), (100.0, 0.0), downstream_xy=(0.0, 400.0))
        self.assertEqual(g["direction"], "S")
        with self.assertRaises(AR.JobError):
            LR.gauge_from_ab((1.0, 1.0), (1.0, 1.0))

    def test_write_inputs(self):
        tmp = tempfile.mkdtemp()
        data = np.full((8, 10), 100.0)
        data[:2, :] = NODATA
        g = Grid(data, 500000.0, 5200080.0, 10.0, NODATA, None)
        st = LR.check_settings({"closed_edges": ["w"], "massint_s": 120})
        gauge = LR.gauge_from_ab((500050.0, 5200050.0), (500050.0, 5200010.0), (500000.0, 5200030.0))
        par = LR.write_inputs(tmp, g, [0, 100.0], [1e-6, 0.0], st, 7200.0, gauge, "c")
        text = open(par).read().splitlines()
        self.assertIn("sim_time 7200", text)
        self.assertIn("massint 120", text)
        self.assertIn("gaugefile rain.gauge", text)
        bci = open(os.path.join(tmp, "rain.bci")).read().splitlines()
        self.assertEqual([b.split()[0] for b in bci], ["N", "S", "E"])         # W closed
        self.assertTrue(all(b.endswith("FREE") for b in bci))
        asc = open(os.path.join(tmp, "rain.dem.asc")).read().splitlines()
        self.assertIn("xllcorner 0.000000", asc)                                # local coordinates (single precision)
        self.assertIn("NODATA_value -9999", asc)
        gl = open(os.path.join(tmp, "rain.gauge")).read().splitlines()
        self.assertEqual(gl[0], "1")
        x, y, d, ln = gl[1].split()
        self.assertEqual(d, "E")
        self.assertAlmostEqual(float(x), 50.0)
        self.assertGreater(float(ln), 0.0)


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Domain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dem = os.path.join(self.tmp, "dem.tif")
        make_dem(self.dem, nx=100, ny=80, cell=30.0)
        self.ring = circle(501500.0 + 900.0, 5198000.0 + 300.0, 800.0)

    def test_terrain_is_the_same_domain_as_the_anuga_job(self):
        grid, _ = AR.read_model_grid(self.dem, (500500, 5197000, 503500, 5199500), 30.0)
        terr, info = LR.model_terrain(grid, [self.ring], 0.0, None, 60.0)
        region = AR.domain_region(grid, [self.ring])
        outer, oinfo = AR.outer_ring(grid, region, 0.0, None, 60.0)
        self.assertEqual(info["simplify_m"], 60.0)
        self.assertTrue(np.allclose(info["ring"], outer))
        want = AR.domain_region(grid, [outer]) & grid.valid()
        rows, cols = np.where(want.any(axis=1))[0], np.where(want.any(axis=0))[0]          # the terrain is cropped to these
        self.assertTrue(((terr.data != NODATA) == want[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]).all())
        self.assertEqual(info["domain_cells"], int(want.sum()))
        self.assertAlmostEqual(info["domain_km2"], want.sum() * 900.0 / 1e6)
        self.assertLess(info["domain_km2"], 2.1)                                 # a circle of radius 800 m, not the extent

    def test_grid_is_cropped_so_the_free_edges_touch_the_domain(self):
        # a NODATA frame would put the FREE edges outside the domain and close the model (found on DWR-2801:
        # Qout 0 for the whole storm). The grid is cropped to the valid cells, on the same cell lattice.
        grid, _ = AR.read_model_grid(self.dem, (500500, 5197000, 503500, 5199500), 30.0)
        terr, info = LR.model_terrain(grid, [self.ring], 0.0, None, 60.0)
        self.assertLess(terr.data.size, grid.data.size)
        self.assertEqual(info["cropped_from"], [grid.ny, grid.nx])
        v = terr.valid()
        self.assertTrue(v[0].any() and v[-1].any() and v[:, 0].any() and v[:, -1].any())
        self.assertEqual(info["edge_valid_cells"], {"N": int(v[0].sum()), "S": int(v[-1].sum()),
                                                    "W": int(v[:, 0].sum()), "E": int(v[:, -1].sum())})
        self.assertTrue(all(n > 0 for n in info["edge_valid_cells"].values()))
        self.assertEqual((terr.x0 - grid.x0) % 30.0, 0.0)
        self.assertEqual((grid.y0 - terr.y0) % 30.0, 0.0)
        r0, c0 = int(round((grid.y0 - terr.y0) / 30.0)), int(round((terr.x0 - grid.x0) / 30.0))
        self.assertTrue(np.array_equal(terr.data, np.where(AR.domain_region(grid, [info["ring"]]) & grid.valid(), grid.data,
                                                           NODATA)[r0:r0 + terr.ny, c0:c0 + terr.nx]))

    def test_geotiff_and_ascii_agree(self):
        grid, _ = AR.read_model_grid(self.dem, (500500, 5197000, 503500, 5199500), 30.0)
        terr, _ = LR.model_terrain(grid, [self.ring])
        p = LR.write_tif(os.path.join(self.tmp, LR.TERRAIN_NAME), terr)
        self.assertEqual(os.path.basename(p), "Model Terrain (LISFLOOD).tif")
        ds = gdal.Open(p)
        self.assertEqual(ds.GetGeoTransform(), (terr.x0, 30.0, 0.0, terr.y0, 0.0, -30.0))
        a = ds.GetRasterBand(1).ReadAsArray()
        self.assertTrue(((a != NODATA) == terr.valid()).all())
        LR.write_inputs(self.tmp, terr, [0, 1.0], [0.0, 0.0], LR.check_settings({}), 100.0)
        back = Grid.read_asc(os.path.join(self.tmp, "rain.dem.asc"))
        self.assertEqual(back.data.shape, terr.data.shape)
        self.assertTrue(np.allclose(np.where(terr.valid(), terr.data, NODATA), back.data, atol=5e-4))

    def test_tiny_domain_is_refused(self):
        grid, _ = AR.read_model_grid(self.dem, (500500, 5197000, 503500, 5199500), 30.0)
        with self.assertRaises(AR.JobError):
            LR.model_terrain(grid, [circle(501000.0, 5198000.0, 20.0)])


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class LauncherAndResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        data = np.full((12, 14), 100.0)
        data[:3, :] = NODATA
        self.terr = Grid(data, 500000.0, 5200120.0, 10.0, NODATA, None)
        self.gauge = LR.gauge_from_ab((500070.0, 5200090.0), (500070.0, 5200020.0), (500000.0, 5200050.0))
        self.par = LR.write_inputs(self.tmp, self.terr, [0, 3600.0], [1e-6, 1e-6], LR.check_settings({"threads": 2}), 7200.0,
                                   self.gauge)

    def test_runs_in_the_job_folder_with_the_runners_arguments(self):
        exe = stand_in_exe(self.tmp)
        cp = launch.run_lisflood(exe, self.par, threads=2, timeout_s=60)
        self.assertEqual(cp.returncode, 0)
        self.assertIn("args ['-v', 'rain.par'] OMP 2", cp.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "results", "rain.max")))
        self.assertIn("args", open(os.path.join(self.tmp, "lisflood.log")).read())

    def test_not_an_executable_is_refused_and_a_timeout_stops_it(self):
        with self.assertRaises(AR.JobError):
            launch.run_lisflood(os.path.join(self.tmp, "nope"), self.par)
        slow = os.path.join(self.tmp, "slow")
        with open(slow, "w") as fh:
            fh.write("#!/bin/sh\nsleep 30\n")
        os.chmod(slow, 0o755)
        from damit_pmp.runner_shared import wallclock
        with self.assertRaises(wallclock.Timeout):
            launch.run_lisflood(slow, self.par, timeout_s=1.0)

    def test_results_are_read_back(self):
        launch.run_lisflood(stand_in_exe(self.tmp, depth=0.12, qout=0.5), self.par, timeout_s=60)
        r = LR.summarize(self.tmp, self.terr, 7200.0, 120.0)
        self.assertAlmostEqual(r["max_depth_m"], 0.12)
        self.assertAlmostEqual(r["wet_area_km2"]["0.05 m"], self.terr.valid().sum() * 100.0 / 1e6)
        self.assertEqual(r["wet_area_km2"]["0.3 m"], 0.0)
        self.assertEqual(r["balance"]["rain_in_m3"], 1000.0)                      # the last, cumulative, rain value
        self.assertEqual(r["balance"]["stored_m3"], 900.0)
        self.assertEqual(r["balance"]["outflow_m3_by_difference"], 100.0)
        self.assertTrue(r["finished"])
        self.assertEqual(r["gauge"]["peak_abs_m3_s"], 0.7)
        self.assertEqual(r["gauge"]["t_peak_s"], 600.0)
        self.assertEqual(r["gauge"]["signed_q_at_peak_m3_s"], -0.7)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, LR.MAX_DEPTH_NAME)))
        with open(os.path.join(self.tmp, LR.RESULTS_NAME)) as fh:
            self.assertEqual(json.load(fh)["storm_depth_mm"], 120.0)
        ds = gdal.Open(os.path.join(self.tmp, LR.MAX_DEPTH_NAME))
        self.assertEqual(ds.GetGeoTransform()[0], self.terr.x0)

    def test_missing_max_file_is_a_clear_error(self):
        with self.assertRaises(AR.JobError) as cm:
            LR.summarize(self.tmp, self.terr, 7200.0, 1.0)
        self.assertIn("lisflood.log", str(cm.exception))

    def test_unfinished_run_is_flagged(self):
        launch.run_lisflood(stand_in_exe(self.tmp), self.par, timeout_s=60)
        self.assertFalse(LR.summarize(self.tmp, self.terr, 20000.0, 1.0)["finished"])


@unittest.skipUnless(HAVE and REAL_EXE, "set DAMIT_PMP_LISFLOOD to a LISFLOOD-FP executable to run the real solver")
class RealExecutable(unittest.TestCase):
    def test_a_five_minute_run_balances(self):
        tmp = tempfile.mkdtemp()
        data = np.full((20, 20), 100.0)
        data += np.linspace(0, 1.0, 20)[None, :]
        terr = Grid(data, 500000.0, 5200200.0, 10.0, NODATA, None)
        par = LR.write_inputs(tmp, terr, [0, 600.0], [1e-5, 1e-5], LR.check_settings({"massint_s": 60}), 600.0)
        cp = launch.run_lisflood(REAL_EXE, par, threads=1, timeout_s=300)
        self.assertEqual(cp.returncode, 0, cp.stdout[-400:])
        r = LR.summarize(tmp, terr, 600.0, 36.0)
        self.assertAlmostEqual(r["balance"]["rain_in_m3"], 1e-5 * 600.0 * 400 * 100.0, delta=1.0)
        self.assertGreater(r["max_depth_m"], 0.0)

    def test_a_masked_domain_drains_through_the_grid_edge(self):
        # the same cropping as the job: a tilted plane inside a polygon, water must reach Qout
        tmp = tempfile.mkdtemp()
        n = 60
        data = np.full((n, n), 400.0) - 0.01 * 10.0 * np.arange(n)[None, :]      # falls to the east
        grid = Grid(data, 500000.0, 5200600.0, 10.0, NODATA, None)
        ring = circle(500300.0, 5200300.0, 250.0)
        terr, info = LR.model_terrain(grid, [ring])
        self.assertGreater(info["edge_valid_cells"]["E"], 0)
        par = LR.write_inputs(tmp, terr, [0, 1200.0], [2e-5, 2e-5], LR.check_settings({"massint_s": 60}), 1800.0)
        cp = launch.run_lisflood(REAL_EXE, par, threads=1, timeout_s=300)
        self.assertEqual(cp.returncode, 0, cp.stdout[-400:])
        r = LR.summarize(tmp, terr, 1800.0, 36.0)
        self.assertGreater(r["balance"]["outflow_m3_from_qout"], 0.0)


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class OutletPipe(unittest.TestCase):
    """0.4.2: the principal outlet as a sink / source pair rated from a pond stage series."""
    OUTLET = {"end_points": [(500050.0, 5200100.0), (500350.0, 5200100.0)], "width_m": 0.9, "invert_elevations": [100.0, 99.0],
              "barrels": 1.0, "assumed": True}

    def terr(self):
        return Grid(np.full((20, 40), 100.0), 500000.0, 5200200.0, 10.0, NODATA, None)

    def test_boyd_rating_is_zero_without_head_rises_and_takes_the_smaller_form(self):
        self.assertEqual(float(LR.boyd_pipe_q(0.0, 0.9)), 0.0)
        self.assertEqual(float(LR.boyd_pipe_q(-1.0, 0.9)), 0.0)
        h = np.array([0.1, 0.5, 1.0, 2.0, 3.0])
        q = LR.boyd_pipe_q(h, 0.9)
        self.assertTrue(np.all(np.diff(q) > 0))
        d, g = 0.9, LR.G
        unsub = 0.421 * g ** 0.5 * d ** 0.87 * h ** 1.63
        sub = 0.530 * g ** 0.5 * d ** 1.87 * h ** 0.63
        self.assertTrue(np.allclose(q, np.minimum(unsub, sub)))
        self.assertTrue(np.allclose(LR.boyd_pipe_q(h, 0.9, 2.0), 2.0 * q))              # barrels
        self.assertGreater(float(LR.boyd_pipe_q(3.0, 0.9)), 1.0)                        # a 36 in pipe at 3 m head: m3/s, not l/s
        self.assertLess(float(LR.boyd_pipe_q(3.0, 0.9)), 10.0)

    def test_flow_series_follows_the_stage_over_the_invert(self):
        t, q = LR.outlet_flow_series([0, 100, 200], [99.0, 100.0, 102.0], self.OUTLET)
        self.assertEqual(q[0], 0.0)
        self.assertEqual(q[1], 0.0)                                  # stage at the invert: no head
        self.assertGreater(q[2], 0.0)
        with self.assertRaises(LR.JobError):
            LR.outlet_flow_series([0], [1.0], self.OUTLET)

    def test_inputs_have_a_sink_and_a_source_and_the_runners_keyword_order(self):
        tmp = tempfile.mkdtemp()
        st = LR.check_settings({})
        q = (np.array([0, 3600.0]), np.array([0.5, 1.5]))
        par = LR.write_inputs(tmp, self.terr(), [0, 600.0], [1e-5, 1e-5], st, 3600.0, outlet=self.OUTLET, outlet_q=q,
                              probe=(500050.0, 5200100.0))
        bci = open(os.path.join(tmp, "rain.bci")).read().splitlines()
        self.assertEqual(bci[0], "P 50.000 100.000 QVAR outlet_in")
        self.assertEqual(bci[1], "P 350.000 100.000 QVAR outlet_out")
        self.assertTrue(any(l.endswith("FREE") for l in bci[2:]))
        bdy = open(os.path.join(tmp, "rain.bdy")).read().split("\n")
        self.assertIn("ASSUMED", bdy[0])
        i = bdy.index("outlet_in")
        self.assertEqual(bdy[i + 1], "2 seconds")
        self.assertAlmostEqual(float(bdy[i + 2].split()[0]), -0.05)                   # m3/s / 10 m cell, negative = sink
        j = bdy.index("outlet_out")
        self.assertAlmostEqual(float(bdy[j + 3].split()[0]), 0.15)                    # positive = source
        lines = open(par).read().splitlines()
        self.assertLess(lines.index("bcifile rain.bci"), lines.index("bdyfile rain.bdy"))
        self.assertIn("stagefile rain.stagepts", lines)
        self.assertEqual(open(os.path.join(tmp, "rain.stagepts")).read().split(), ["1", "50.000", "100.000"])
        with self.assertRaises(LR.JobError):
            LR.write_inputs(tmp, self.terr(), [0, 600.0], [1e-5, 1e-5], st, 3600.0, outlet=self.OUTLET)

    def test_no_outlet_no_bdy_no_stage_lines(self):
        lines = LR.par_lines(LR.check_settings({}), 3600.0)
        self.assertFalse(any(l.startswith(("bdyfile", "stagefile")) for l in lines))

    def test_probe_stage_is_elevation_plus_depth(self):
        p = os.path.join(tempfile.mkdtemp(), "rain.stage")
        open(p, "w").write("Stage output, depth (m). Stage locations from: rain.stagepts\n\nStage information (stage,x,y,elev):\n"
                            "1\t50.0000\t100.0000\t321.5000\n\nOutput, depths:\nTime; stages 1 to 1\n   10.000    0.0100\n  70.000    0.2500\n")
        t, z = LR.read_probe_stage(p)
        self.assertEqual(list(t), [10.0, 70.0])
        self.assertTrue(np.allclose(z, [321.51, 321.75]))
        self.assertIsNone(LR.read_probe_stage(p + ".none"))


@unittest.skipUnless(HAVE and REAL_EXE, "set DAMIT_PMP_LISFLOOD to a LISFLOOD-FP executable to run the real solver")
class RealOutlet(unittest.TestCase):
    def test_the_source_wets_the_outlet_cell_and_the_probe_stage_is_written(self):
        # a closed flat basin: the pipe's sink / source pair puts 50 L/s at the far cell, well above the rain alone
        tmp = tempfile.mkdtemp()
        data = np.full((20, 40), 100.0)
        terr = Grid(data, 500000.0, 5200200.0, 10.0, NODATA, None)
        o = dict(OutletPipe.OUTLET)
        q = (np.array([0, 1200.0]), np.array([0.05, 0.05]))
        st = LR.check_settings({"massint_s": 60, "closed_edges": ("N", "S", "E", "W")})
        par = LR.write_inputs(tmp, terr, [0, 300.0], [2e-5, 2e-5], st, 1200.0, outlet=o, outlet_q=q, probe=(500050.0, 5200100.0))
        cp = launch.run_lisflood(REAL_EXE, par, threads=1, timeout_s=300)
        self.assertEqual(cp.returncode, 0, cp.stdout[-400:])
        r = LR.summarize(tmp, terr, 1200.0, 72.0)
        mx = Grid.read_asc(os.path.join(tmp, "results", "rain.max")).data
        self.assertGreater(mx[10, 35], 0.02)                                  # the source cell is wet (50 L/s for 20 min; the rain alone is 6 mm)
        self.assertIn("probe_stage", r)
        self.assertTrue(os.path.isfile(os.path.join(tmp, LR.PROBE_STAGE_NAME)))


if __name__ == "__main__":
    unittest.main()
