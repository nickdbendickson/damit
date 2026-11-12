"""Tests for the two DWR-2801 findings fixed in run_digest 1.3.1 / lumo_watch 1.3.1: PASS_UNFINISHED at 99 % (the .mass output
interval) and the cost of pass_end receptor sampling on 88k structures. Synthetic fixtures only; no model, no Ollama."""
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LUMO = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(LUMO, "..", ".."))
sys.path.insert(0, os.path.join(LUMO, "tools"))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import fixture_run as FX  # noqa: E402
import lumo_watch as LW  # noqa: E402
import run_digest as RD  # noqa: E402
from strict import StrictCase, jdump, jload  # noqa: E402

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
needs_numpy = unittest.skipUnless(HAVE_NUMPY, "numpy")


class Base(StrictCase):
    def setUp(self):
        super(Base, self).setUp()
        self.root = tempfile.mkdtemp(prefix="lumo_2801_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = LW.settings()
        self.cfg.update(first_token_s=5.0, idle_s=1.0, wait_s=0.0)

    def flags(self, d, fid):
        return [f for f in d["flags"] if f["id"] == fid]


# --------------------------------------------------------------------------------------- item 1: PASS_UNFINISHED
@needs_numpy
class TestMassIntervalTolerance(Base):
    def make(self, sim_time, massint=True, finish=True, report=False, progress=True, passes=2):
        """Pass 1 of a run whose .mass ends at 3000 s (rows every 300 s), planned sim_time `sim_time`."""
        run, dam = FX.make_run(self.root, report=report, passes=passes, progress=progress, layout="work")
        d = os.path.join(run, "model", "run01_50m")
        FX.write(os.path.join(d, "run.par"), "DEMfile run.dem.asc\nsim_time %s\n%s" % (sim_time, "massint 300\n" if massint else ""))
        if not finish:
            FX.write(os.path.join(d, "lisflood.log"), "Start Time: 0:00:01\n")
        return run, dam

    def digest(self, run, dam, n=1):
        return RD.build_digest(run, "pass_end", dam_folder=dam, upto_pass=n)

    def test_the_dwr_2801_case_a_clean_pass_99_percent_of_sim_time_is_not_flagged(self):
        run, dam = self.make(3250)                      # last sample 3000 of 3250 = 92 %, 250 s short, massint 300
        p = self.digest(run, dam)["checks"]["passes"][0]
        self.assertLess(p["progress"], 0.99)
        self.assertEqual((p["mass_interval_s"], p["short_s"], p["within_mass_interval"]), (300.0, 250.0, True))
        self.assertEqual(self.flags(self.digest(run, dam), "PASS_UNFINISHED"), [])
        # the real numbers: 24,308.8 s of 24,561 s = 98.97 %
        self.assertAlmostEqual(24308.805 / 24561, 0.9897, 3)

    def test_a_genuinely_short_pass_is_still_flagged(self):
        run, dam = self.make(3700)                      # 700 s short: more than one interval, with a Finish line
        f = self.flags(self.digest(run, dam), "PASS_UNFINISHED")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "WATCH")
        self.assertIn("ended early", f[0]["title"])

    def test_the_boundary_is_one_interval_plus_a_second(self):
        for sim, flagged in ((3300, False), (3301, False), (3302, True)):
            shutil.rmtree(self.root)
            os.makedirs(self.root)
            run, dam = self.make(sim)
            self.assertEqual(bool(self.flags(self.digest(run, dam), "PASS_UNFINISHED")), flagged, sim)

    def test_the_interval_comes_from_the_last_two_samples_without_massint(self):
        run, dam = self.make(3250, massint=False)
        p = self.digest(run, dam)["checks"]["passes"][0]
        self.assertEqual(p["mass_interval_s"], 300.0)           # 2700 -> 3000
        self.assertEqual(self.flags(self.digest(run, dam), "PASS_UNFINISHED"), [])
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        run, dam = self.make(3700, massint=False)
        self.assertEqual(len(self.flags(self.digest(run, dam), "PASS_UNFINISHED")), 1)

    def test_no_finish_line_needs_the_runner_or_a_later_pass_to_agree(self):
        # not the last pass: a later pass started, so the Runner moved on
        run, dam = self.make(3250, finish=False)
        self.assertEqual(self.flags(self.digest(run, dam, 2), "PASS_UNFINISHED"), [])
        # the last pass, still running (no report, nothing recorded): judged as before, i.e. running, no flag at all
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        run, dam = self.make(3250, finish=False, progress=False, passes=1)
        self.assertEqual(self.flags(self.digest(run, dam), "PASS_UNFINISHED"), [])
        # the last pass of a FINISHED run (report) with no Finish line and a real shortfall is still a PROBLEM
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        run, dam = self.make(3700, finish=False, report=True, passes=1)
        f = self.flags(RD.build_digest(run, "run_end", dam_folder=dam), "PASS_UNFINISHED")
        self.assertEqual([x["severity"] for x in f], ["PROBLEM"])

    def test_no_finish_line_but_recorded_by_the_runner_and_within_the_interval_is_complete(self):
        run, dam = self.make(3250, finish=False, report=True, passes=1)
        self.assertEqual(self.flags(RD.build_digest(run, "run_end", dam_folder=dam), "PASS_UNFINISHED"), [])
        p = RD.build_digest(run, "run_end", dam_folder=dam)["checks"]["passes"][0]
        self.assertTrue(p["runner_recorded"])

    def test_the_stalled_last_pass_is_still_a_stall(self):
        run, dam = self.make(3250, finish=False, progress=False, passes=1)
        mp = os.path.join(run, "model", "run01_50m", "results", "run.mass")
        os.utime(mp, (time.time() - 5000, time.time() - 5000))
        FX.write(os.path.join(run, "model", "run01_50m", "run.par"), "sim_time 30000\nmassint 300\n")
        d = RD.build_digest(run, "pass_end", dam_folder=dam, upto_pass=1)
        self.assertEqual(len(self.flags(d, "STALL")), 1)


# --------------------------------------------------------------------------------------- item 2: cheap receptors
def legacy_receptor_check(grid, points, th=RD.THRESHOLDS):
    """The 1.3.0 per-point version, kept here as the reference the vectorised one must equal."""
    nodata, dry_next, outside, n = [], [], 0, 0
    a = grid.data
    for pid, x, y in points:
        r, c = grid.rowcol(x, y)
        if not (0 <= r < a.shape[0] and 0 <= c < a.shape[1]):
            outside += 1
            continue
        n += 1
        v = a[r, c]
        nb = RD.neighbours_max(a, r, c)
        if not np.isfinite(v):
            if nb >= th["wet_ft"]:
                nodata.append((pid, round(nb, 2)))
        elif v < th["wet_ft"] and nb >= th["near_wet_ft"]:
            dry_next.append((pid, round(nb, 2)))
    return {"sampled": n, "outside": outside, "nodata_next_to_wet": nodata, "dry_next_to_wet": dry_next}


def synthetic(n_points=88000, size=1000, cell=50.0, seed=7):
    """A size x size depth grid (ft) with blobs, NoData holes and trace cells, and n points over it and beyond it."""
    rng = np.random.RandomState(seed)
    a = np.zeros((size, size))
    for _ in range(40):
        r, c = rng.randint(50, size - 50, 2)
        a[r - 20:r + 20, c - 20:c + 20] = rng.uniform(0.5, 6.0)
    a[rng.rand(size, size) < 0.01] = np.nan                   # holes
    a[(rng.rand(size, size) < 0.01) & (a == 0)] = 0.03        # traces
    g = RD.Grid(a, 0.0, size * cell, cell)
    x = rng.uniform(-2000, size * cell + 2000, n_points)
    y = rng.uniform(-2000, size * cell + 2000, n_points)
    pts = [("s%d" % i, float(x[i]), float(y[i])) for i in range(n_points)]
    return g, pts


@needs_numpy
class TestVectorisedSampling(Base):
    def test_same_result_and_order_as_the_per_point_version(self):
        g, pts = synthetic(n_points=6000, size=300)
        want = legacy_receptor_check(g, pts)
        got = RD.receptor_check(g, pts)
        self.assertEqual(got, want)
        self.assertGreater(len(want["nodata_next_to_wet"]), 0)
        self.assertGreater(len(want["dry_next_to_wet"]), 0)
        self.assertGreater(want["outside"], 0)

    def test_edges_and_an_empty_or_dry_grid(self):
        g = RD.Grid(np.zeros((4, 4)), 0.0, 200.0, 50.0)
        self.assertEqual(RD.receptor_check(g, [("a", 10, 10), ("b", 999, 999)]),
                         {"sampled": 1, "outside": 1, "nodata_next_to_wet": [], "dry_next_to_wet": []})
        self.assertEqual(RD.receptor_check(g, []), {"sampled": 0, "outside": 0, "nodata_next_to_wet": [], "dry_next_to_wet": []})
        a = np.zeros((4, 4))
        a[0, 0] = 2.0
        a[0, 1] = np.nan
        g = RD.Grid(a, 0.0, 200.0, 50.0)                         # a NoData cell beside the wet corner; a dry cell beside it
        got = RD.receptor_check(g, [("hole", 75, 175), ("dry", 25, 125), ("far", 175, 25)])
        self.assertEqual(got["nodata_next_to_wet"], [("hole", 2.0)])
        self.assertEqual(got["dry_next_to_wet"], [("dry", 2.0)])
        self.assertEqual(got, legacy_receptor_check(g, [("hole", 75, 175), ("dry", 25, 125), ("far", 175, 25)]))

    def test_micro_benchmark_88k_structures(self):
        """DWR-2801: 88,734 structures. One hook's sampling on a 1000 x 1000 grid must stay well under a second (the per-point
        version needs many seconds on the same input); the timings are printed for the PR."""
        g, pts = synthetic(88734, 1000)
        ps = RD.as_pointset(pts)
        t0 = time.perf_counter()
        got = RD.receptor_check(g, ps)
        t_new = time.perf_counter() - t0
        sub = pts[:8000]
        t0 = time.perf_counter()
        legacy_receptor_check(g, sub)
        t_old_8k = time.perf_counter() - t0
        est_old = t_old_8k * len(pts) / len(sub)
        print("\n[bench] vectorised %.3f s for %d points; per-point %.3f s for 8000 (~%.1f s for all)" % (
            t_new, len(pts), t_old_8k, est_old))
        self.assertEqual(got["sampled"] + got["outside"], 88734)
        self.assertLess(t_new, 1.5)
        self.assertLess(t_new * 3, est_old)

    def test_the_points_are_loaded_once_per_layer(self):
        layer = os.path.join(self.root, "structures.gpkg")
        with open(layer, "w") as f:
            f.write("x")
        calls = []

        def fake(path, wkt, **k):
            calls.append(wkt)
            return [("a", 1.0, 2.0), ("b", 3.0, 4.0)]
        old = RD.load_points_ogr
        RD.load_points_ogr = fake
        self.addCleanup(setattr, RD, "load_points_ogr", old)
        first = RD.cached_points(layer, "WKT1")
        again = RD.cached_points(layer, "WKT1")
        self.assertIs(first, again)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first.ids, ["a", "b"])
        self.assertEqual(first.x.tolist(), [1.0, 3.0])
        RD.cached_points(layer, "WKT2")                              # another CRS: read again
        self.assertEqual(len(calls), 2)
        time.sleep(0.01)
        with open(layer, "w") as f:
            f.write("changed layer")                                 # an edited layer: read again
        RD.cached_points(layer, "WKT1")
        self.assertEqual(len(calls), 3)
        RD.load_points_ogr = lambda *a, **k: None                    # no GDAL: None, and nothing cached
        self.assertIsNone(RD.cached_points(layer, "WKT3"))

    def test_every_pass_hook_of_a_run_reads_the_layer_once(self):
        run, dam = FX.make_run(self.root, report=False, layout="work", progress=True)
        layer = os.path.join(self.root, "structures.gpkg")
        with open(layer, "w") as f:
            f.write("x")
        calls = []
        rows = FX.receptor_rows()

        def fake(path, wkt, **k):
            calls.append(1)
            return rows
        old = RD.load_points_ogr
        RD.load_points_ogr = fake
        self.addCleanup(setattr, RD, "load_points_ogr", old)
        for n in (1, 2, 3):
            d = RD.build_digest(run, "pass_end", dam_folder=dam, structures_path=layer, upto_pass=n)
            self.assertIsNotNone(d["checks"]["receptors"])
        self.assertEqual(len(calls), 1)


@needs_numpy
class TestEveryNthPass(Base):
    def run_hooks(self, every, complete=False, passes=4):
        run, dam = FX.make_run(self.root, report=complete, layout="work", progress=True, progress_complete=complete, passes=passes)
        pts = FX.write_points(self.root)
        if not complete:
            s = jload(os.path.join(run, "run_setup.json"))
            s["status"] = "running"
            jdump(s, os.path.join(run, "run_setup.json"))
        cfg = dict(self.cfg, pass_receptor_every=every)
        out = {}
        for n in range(1, passes + 1):
            r = LW.run_event(run, "pass_end", os.path.join(self.root, "w"), pass_no=n, lumo=False, cfg=cfg, dam_folder=dam,
                             points_path=pts)
            out[n] = r["digest"]
        end = LW.run_event(run, "run_end", os.path.join(self.root, "w"), lumo=False, cfg=cfg, dam_folder=dam, points_path=pts)
        return out, end["digest"]

    def sampled(self, d):
        return d["checks"]["receptors"] is not None

    def test_default_samples_every_second_pass_and_always_at_run_end(self):
        self.assertEqual(LW.settings()["pass_receptor_every"], 2)
        out, end = self.run_hooks(2)
        self.assertEqual({n: self.sampled(d) for n, d in out.items()}, {1: False, 2: True, 3: False, 4: True})
        self.assertIn("not sampled", out[1]["checks"]["receptors_skipped"])
        self.assertIsNone(out[2]["checks"]["receptors_skipped"])
        self.assertTrue(self.sampled(end))

    def test_every_one_every_pass_and_zero_never_mid_run(self):
        out, end = self.run_hooks(1, passes=3)
        self.assertTrue(all(self.sampled(d) for d in out.values()))
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        out, end = self.run_hooks(0, passes=3)
        self.assertFalse(any(self.sampled(d) for d in out.values()))
        self.assertTrue(self.sampled(end))

    def test_a_replayed_hook_on_a_finished_run_always_samples(self):
        out, end = self.run_hooks(2, complete=True, passes=3)
        self.assertTrue(all(self.sampled(d) for d in out.values()))

    def test_environment_and_cli_setting(self):
        os.environ["LUMO_WATCH_PASS_RECEPTOR_EVERY"] = "3"
        self.addCleanup(os.environ.pop, "LUMO_WATCH_PASS_RECEPTOR_EVERY", None)
        self.assertEqual(LW.settings()["pass_receptor_every"], 3)
        os.environ["LUMO_WATCH_PASS_RECEPTOR_EVERY"] = "-4"
        self.assertEqual(LW.settings()["pass_receptor_every"], 0)

    def test_an_explicit_sample_receptors_wins(self):
        run, dam = FX.make_run(self.root, report=False, layout="work", progress=True)
        pts = FX.write_points(self.root)
        r = LW.run_event(run, "pass_end", os.path.join(self.root, "w"), pass_no=1, lumo=False,
                         cfg=dict(self.cfg, pass_receptor_every=2), dam_folder=dam, points_path=pts, sample_receptors=True)
        self.assertIsNotNone(r["digest"]["checks"]["receptors"])


class TestNice(Base):
    def test_watch_lowers_its_priority_without_failing(self):
        calls = []
        old = getattr(os, "nice", None)
        if old is None:
            self.skipTest("no os.nice")
        os.nice = lambda n: (calls.append(n), 5 + n)[1] if n else 5
        self.addCleanup(setattr, os, "nice", old)
        self.assertEqual(LW.settings()["pass_nice"], 19)
        self.assertEqual(LW.lower_priority(19), 19)
        self.assertEqual(calls, [14])                           # from nice 5 up to 19
        calls[:] = []
        self.assertEqual(LW.lower_priority(3), 5)               # never lowers the level
        self.assertEqual(calls, [])
        self.assertIsNone(LW.lower_priority(0))

        def boom(n):
            raise OSError("no")
        os.nice = boom
        self.assertIsNone(LW.lower_priority(19))


if __name__ == "__main__":
    unittest.main()
