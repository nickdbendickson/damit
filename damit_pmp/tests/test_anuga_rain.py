"""damit_pmp:anugarain: the ANUGA rain-on-grid job on the runner's gmsh mesh (no QGIS, no network).

Needs numpy, scipy and GDAL (skips otherwise). gmsh and ANUGA are not needed here: the launcher is
tested with stand-in scripts, the real mesher / generated script only when DAMIT_PMP_ANUGA_PYTHON names an
ANUGA Python that has gmsh (set it on a machine that has one: the checks then run the real mesher and the
script's --dry check; nothing is simulated)."""
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
    from osgeo import gdal, osr
    gdal.UseExceptions()
    HAVE = True
except ImportError:                                            # pragma: no cover
    HAVE = False

if HAVE:
    from damit_pmp import anugarain as AR
    from damit_pmp import launch
    from damit_pmp.runner_shared import gmsh_mesher as gm
    from damit_pmp.runner_shared import terrain

ANUGA_PY = os.environ.get("DAMIT_PMP_ANUGA_PYTHON", "")


def make_dem(path, nx=120, ny=100, cell=30.0, x0=500000.0, y0=5200000.0, slope=0.01, epsg=26914, nodata=-9999.0):
    """A plane falling to the south-east (z = 400 - slope * (x + (y0 - y)) ) with a shallow valley."""
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 - (np.arange(ny) + 0.5) * cell
    X, Y = np.meshgrid(xs, ys)
    z = 400.0 - slope * ((X - x0) + (y0 - Y)) - 3.0 * np.exp(-((Y - (y0 - ny * cell / 2)) / 150.0) ** 2)
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(z.astype("float32"))
    ds.FlushCache()
    return z


def circle(cx, cy, r, n=48):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Settings(unittest.TestCase):
    def test_defaults_are_the_runners(self):
        s = AR.check_settings({})
        self.assertEqual((s["cell_m"], s["manning_n"], s["algorithm"], s["edge_bc"], s["yieldstep_s"], s["gmsh_timeout_s"]),
                         (10.0, 0.06, "DE0", "outflow", 300.0, 600.0))
        self.assertEqual(gm.default_sizes()["max_area_m2"], 20000.0)       # the mesher's own, untouched

    def test_bad_values_name_the_key(self):
        for kw, word in (({"cell_m": 0.1}, "cell_m"), ({"algorithm": "DE9"}, "algorithm"), ({"edge_bc": "wall"}, "edge_bc"),
                         ({"manning_n": 0}, "manning_n"), ({"threads": -1}, "threads")):
            with self.assertRaises(AR.JobError) as cm:
                AR.check_settings(kw)
            self.assertIn(word, str(cm.exception))

    def test_spec_has_no_sizing_unless_asked(self):
        spec = AR.mesh_spec(circle(0, 0, 1000), None, None, 1, None)
        self.assertEqual(sorted(spec), ["channel", "lines", "outer", "points", "threads"])
        spec = AR.mesh_spec(circle(0, 0, 1000), None, None, 1, {"max_area_m2": 40000, "line_min_area_m2": None})
        self.assertEqual(spec["max_area_m2"], 40000.0)
        self.assertNotIn("line_min_area_m2", spec)

    def test_bad_sizing_is_the_mesher_message(self):
        with self.assertRaises(AR.JobError) as cm:
            AR.mesh_spec(circle(0, 0, 1000), None, None, 1, {"max_area_m2": -5})
        self.assertIn("max_area_m2 must be a positive number", str(cm.exception))
        with self.assertRaises(AR.JobError) as cm:                  # grade distance must reach past DistMin
            AR.mesh_spec(circle(0, 0, 1000), None, None, 1, {"grade_dist_m": 30})
        self.assertIn("grade_dist_m", str(cm.exception))


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class RateSeries(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "r.csv")
        with open(p, "w") as fh:
            fh.write(text)
        return p

    def test_reads_the_raingrid_csv(self):
        t, r = AR.read_rate_csv(self.write("time_s,rate_m_per_s\n0,1e-7\n3600,2e-7\n3601,0\n"))
        self.assertEqual(list(t), [0, 3600, 3601])
        self.assertAlmostEqual(AR.rain_depth_m(t, r), (1e-7 + 2e-7) / 2 * 3600 + 1e-7, places=9)

    def test_rejects_mm_per_hr_and_junk(self):
        for text in ("time_s,rate\n0,50\n3600,60\n", "time_s,r\n0,1e-7\n", "time_s,r\n10,1e-7\n5,1e-7\n",
                     "time_s,r\n0,-1e-7\n10,1e-7\n", "nonsense"):
            with self.assertRaises(AR.JobError, msg=text):
                AR.read_rate_csv(self.write(text))


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Domain(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.dem = os.path.join(self.d, "dem.tif")
        make_dem(self.dem)
        self.cx, self.cy = 500000 + 60 * 30.0, 5200000 - 50 * 30.0

    def grid(self, cell=30.0, rad=1000.0):
        b = (self.cx - rad - 60, self.cy - rad - 60, self.cx + rad + 60, self.cy + rad + 60)
        return AR.read_model_grid(self.dem, b, cell)

    def test_read_model_grid_snaps_to_the_cell(self):
        g, info = self.grid(cell=40.0)
        self.assertEqual(g.dx, 40.0)
        self.assertEqual(g.x0 % 40.0, 0.0)
        self.assertEqual(g.y0 % 40.0, 0.0)
        self.assertTrue(g.valid().all())
        self.assertEqual(info["native_cell_m"], 30.0)

    def test_geographic_dem_is_refused(self):
        p = os.path.join(self.d, "geo.tif")
        make_dem(p, epsg=4326, cell=0.001, x0=-97.0, y0=47.0)
        with self.assertRaises(AR.JobError) as cm:
            AR.read_model_grid(p, (-96.99, 46.9, -96.95, 46.99), 30.0)
        self.assertIn("projected", str(cm.exception))

    def test_outer_ring_is_the_basin_outline(self):
        g, _ = self.grid()
        ring0 = circle(self.cx, self.cy, 800.0)
        region = AR.domain_region(g, [ring0])
        outer, info = AR.outer_ring(g, region)
        area = 0.5 * abs(np.dot(outer[:, 0], np.roll(outer[:, 1], -1)) - np.dot(outer[:, 1], np.roll(outer[:, 0], -1)))
        self.assertAlmostEqual(area / (np.pi * 800.0 ** 2), 1.0, delta=0.08)
        self.assertGreater(len(outer), 8)
        self.assertEqual(info["simplify_m"], 30.0)                  # max(min(0, 3 dx), dx): the runner's tol

    def test_outer_ring_matches_the_runners_mesh_polygons(self):
        """anuga_model.mesh_polygons (the runner's outer ring rule) on the same region, no buffer."""
        from damit_runner.core import anuga_model as M

        class St:
            buffer_m = 0.0
            near_field_radius_m = 1609.0
        g, _ = self.grid()
        region = AR.domain_region(g, [circle(self.cx, self.cy, 800.0)])
        ours, _ = AR.outer_ring(g, region, 0.0, (self.cx, self.cy))
        theirs, _fine = M.mesh_polygons(g, region & g.valid(), (self.cx, self.cy), St())
        self.assertTrue(np.allclose(ours, theirs), "the outer ring differs from the runner's mesh_polygons")

    def test_clip_matches_the_runners(self):
        from damit_runner.core import anuga_model as M
        ring = circle(0, 0, 500.0)
        lines = [np.array([[-800.0, 0], [-400, 0], [0, 0], [400, 0], [800, 0]]), np.array([[0.0, 0], [10, 10]])]
        a = AR.clip_lines_to_polygon(lines, ring)
        b = M.clip_lines_to_polygon(lines, ring)
        self.assertEqual(len(a), len(b))
        for x, y in zip(a, b):
            self.assertTrue(np.allclose(x, y))

    def test_flow_path_runs_downhill_inside_the_domain(self):
        g, _ = self.grid(rad=1200.0)
        region = AR.domain_region(g, [circle(self.cx, self.cy, 1000.0)])
        outer, _ = AR.outer_ring(g, region)
        path, length = AR.flow_path(g, outer, (self.cx - 500.0, self.cy + 300.0))
        self.assertTrue(path)
        z = g.sample_bilinear(np.array([p[0] for p in path[0]]), np.array([p[1] for p in path[0]]))
        self.assertLess(z[-1], z[0])
        ref, _ = terrain.trace_downstream(g, (self.cx - 500.0, self.cy + 300.0), 4.0 * max(g.nx, g.ny) * g.dx)
        self.assertGreater(length, 500.0)
        self.assertGreater(len(ref), 5)

    def test_factor_is_resampled_to_the_model_grid(self):
        g, _ = self.grid()
        fp = os.path.join(self.d, "f.tif")
        make_dem(fp, epsg=26914)                                    # same CRS; values ~ 400 -> factor must be >= 0
        a, st = AR.read_factor_on_grid(fp, g)
        self.assertEqual(a.shape, (g.ny, g.nx))
        self.assertTrue(st["max"] > 300)
        neg = os.path.join(self.d, "neg.tif")
        make_dem(neg, slope=5.0)                                    # goes negative
        with self.assertRaises(AR.JobError):
            AR.read_factor_on_grid(neg, g)

    def test_fine_elevation_only_when_the_dem_is_finer(self):
        g, info = self.grid(cell=60.0)
        out = os.path.join(self.d, "fine.npy")
        job = AR.read_fine_elevation(self.dem, g, info["native_cell_m"], out)
        self.assertEqual(job["elev_fine_dx"], 30.0)
        self.assertEqual(np.load(out).shape, (int(g.ny * 2), int(g.nx * 2)))
        g30, info30 = self.grid(cell=30.0)
        self.assertIsNone(AR.read_fine_elevation(self.dem, g30, info30["native_cell_m"], out))   # not finer: the model grid


@unittest.skipUnless(HAVE, "numpy / scipy / GDAL not installed")
class Files(unittest.TestCase):
    def test_job_script_and_runner_files(self):
        d = tempfile.mkdtemp()
        dem = os.path.join(d, "dem.tif")
        make_dem(dem)
        g, _ = AR.read_model_grid(dem, (500000, 5196000, 503000, 5200000), 30.0)
        st = AR.check_settings({"cell_m": 30.0})
        p = AR.write_job(d, g, np.array([0, 3600.0]), np.array([1e-7, 1e-7]), st, 7200.0, factor=np.full(g.data.shape, 1.1))
        j = np.load(p)
        for k in ("dem", "dem_x0", "dem_y0", "dem_dx", "algorithm", "threads", "manning_n", "edge_bc", "sim_time",
                  "yieldstep", "rain_t", "rain_rate", "factor"):
            self.assertIn(k, j.files)
        self.assertEqual(str(j["edge_bc"]), "outflow")
        files = AR.copy_script_files(d)
        self.assertEqual(files[0], "run_anuga_rain.py")
        for f in AR.SCRIPT_FILES:
            self.assertEqual(AR.sha256_file(os.path.join(d, f)), AR.sha256_file(os.path.join(AR.HERE, "runner_shared", f)))
        compile(open(os.path.join(d, "run_anuga_rain.py")).read(), "run_anuga_rain.py", "exec")

    def test_msh2_roundtrip_text(self):
        d = tempfile.mkdtemp()
        pts = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
        AR.write_msh2(os.path.join(d, "m.msh"), pts, np.array([[0, 1, 2]]))
        txt = open(os.path.join(d, "m.msh")).read().split("\n")
        self.assertEqual(txt[0], "$MeshFormat")
        self.assertIn("1 2 2 1 1 1 2 3", txt)
        self.assertTrue(AR.write_triangles_geojson(os.path.join(d, "t.geojson"), pts, np.array([[0, 1, 2]])))

    def test_runner_sources_are_the_pinned_copies(self):
        src = AR.runner_sources()
        self.assertEqual(sorted(src), sorted(AR.RUNNER_FILES))


STUB_OK = textwrap.dedent('''
    import json, sys
    import numpy as np
    np.savez(sys.argv[2], mesh_points=np.zeros((3, 2)), mesh_triangles=np.array([[0, 1, 2]]),
             mesh_boundary=np.zeros((0, 2), int), mesh_stats=json.dumps({"triangles": 1}))
    print("MESHOK " + json.dumps({"triangles": 1}))
''')
STUB_BAD = "import sys\nprint('MESHERROR min angle 3 deg is below the gate')\nsys.exit(3)\n"
STUB_SLOW = "import time\ntime.sleep(60)\n"


@unittest.skipUnless(HAVE and os.name == "posix", "numpy / posix needed")
class Launcher(unittest.TestCase):
    """damit_pmp/launch.py with stand-in mesher scripts (the real one needs gmsh): the runner's make_gmsh_mesh
    wording and its wall-clock timeout."""

    def stub(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "mesher.py")
        with open(p, "w") as fh:
            fh.write(text)
        return d, p

    def test_ok(self):
        d, m = self.stub(STUB_OK)
        stats, note = launch.run_mesher(sys.executable, os.path.join(d, "in.json"), os.path.join(d, "o.npz"), 30, mesher=m)
        self.assertEqual((stats, note), ({"triangles": 1}, "ok"))

    def test_quality_gate_failure_is_reported(self):
        d, m = self.stub(STUB_BAD)
        stats, note = launch.run_mesher(sys.executable, os.path.join(d, "in.json"), os.path.join(d, "o.npz"), 30, mesher=m)
        self.assertIsNone(stats)
        self.assertIn("min angle 3 deg is below the gate", note)

    def test_timeout_stops_the_process(self):
        d, m = self.stub(STUB_SLOW)
        stats, note = launch.run_mesher(sys.executable, os.path.join(d, "in.json"), os.path.join(d, "o.npz"), 1, mesher=m)
        self.assertIsNone(stats)
        self.assertIn("timeout", note)

    def test_python_must_be_an_executable_file(self):
        for bad in ("", "/no/such/python", tempfile.mkdtemp()):
            with self.assertRaises(AR.JobError):
                launch.check_python(bad)
        d = tempfile.mkdtemp()
        f = os.path.join(d, "x")
        open(f, "w").write("")
        os.chmod(f, stat.S_IRUSR)
        with self.assertRaises(AR.JobError):
            launch.check_python(f)

    def test_clean_env_drops_qgis_python_variables(self):
        env = launch.clean_env({"PYTHONHOME": "x", "PYTHONPATH": "y", "QGIS_PREFIX_PATH": "z", "PATH": "/bin"})
        self.assertEqual(env, {"PATH": "/bin"})

    def test_run_script_runs_in_its_folder(self):
        d, m = self.stub("import os, sys\nprint(os.getcwd(), sys.argv[1:])\n")
        cp = launch.run_script(sys.executable, m, ["--dry"], timeout_s=30)
        self.assertEqual(cp.returncode, 0)
        self.assertIn("['--dry']", cp.stdout)
        self.assertIn(os.path.realpath(d), os.path.realpath(cp.stdout.split(" [")[0]))


@unittest.skipUnless(HAVE and ANUGA_PY, "set DAMIT_PMP_ANUGA_PYTHON to an ANUGA Python with gmsh to run the real mesher")
class RealMesherAndDryCheck(unittest.TestCase):
    """The runner's gmsh mesher on a synthetic basin, then the generated script's --dry (no evolve)."""

    def test_mesh_and_dry_check(self):
        d = tempfile.mkdtemp()
        dem = os.path.join(d, "dem.tif")
        make_dem(dem)
        cx, cy = 500000 + 60 * 30.0, 5200000 - 50 * 30.0
        g, _ = AR.read_model_grid(dem, (cx - 1100, cy - 1100, cx + 1100, cy + 1100), 30.0)
        outer, _ = AR.outer_ring(g, AR.domain_region(g, [circle(cx, cy, 900.0)]), 0.0, (cx - 400, cy + 200))
        chan, _ = AR.flow_path(g, outer, (cx - 400.0, cy + 200.0))
        spec = AR.mesh_spec(outer, chan, [(cx - 400.0, cy + 200.0)], 1, {"max_area_m2": 20000.0})
        AR.write_json(os.path.join(d, AR.SPEC_NAME), spec)
        t, r = np.array([0.0, 3600.0, 3601.0]), np.array([2e-7, 2e-7, 0.0])
        st = AR.check_settings({"cell_m": 30.0})
        AR.write_job(d, g, t, r, st, 7200.0, factor=np.full(g.data.shape, 1.25))
        AR.copy_script_files(d)
        stats, note = launch.run_mesher(ANUGA_PY, os.path.join(d, AR.SPEC_NAME), os.path.join(d, AR.MESH_NAME), 300)
        self.assertIsNotNone(stats, note)
        self.assertGreaterEqual(stats["min_angle_deg"], 20.0)
        cp = launch.run_script(ANUGA_PY, os.path.join(d, "run_anuga_rain.py"), ["--dry"], timeout_s=600)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        rec = json.load(open(os.path.join(d, "anuga_rain_dry_check.json")))
        depth_mm = AR.rain_depth_m(t, r) * 1000.0
        self.assertAlmostEqual(rec["storm_depth_mm"], depth_mm, places=6)
        self.assertAlmostEqual(rec["storm_volume_check_mm_over_area"], depth_mm * 1.25, delta=0.001 * depth_mm)
        self.assertEqual(rec["evolved_steps"], 0)
        self.assertEqual(rec["boundary"], "outflow")
        self.assertEqual(rec["rate_operator_rate_type"], "x,y,t")
        # two short steps (a few seconds of ANUGA; this test only runs where DAMIT_PMP_ANUGA_PYTHON is set): the
        # rain put on the mesh equals the exact series volume and the balance closes
        cp = launch.run_script(ANUGA_PY, os.path.join(d, "run_anuga_rain.py"), ["--steps", "2"], timeout_s=600)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        run = json.load(open(os.path.join(d, "anuga_rain_run.json")))
        self.assertEqual(run["evolved_steps"], 2)
        b = run["balance"]
        self.assertAlmostEqual(b["time_s"], 600.0)
        self.assertAlmostEqual(b["rain_in_m3"], b["anuga_rate_operator_volume_m3"], delta=0.001 * b["rain_in_m3"])
        self.assertLess(abs(b["residual_m3"]), 0.001 * b["rain_in_m3"])


if __name__ == "__main__":
    unittest.main()
