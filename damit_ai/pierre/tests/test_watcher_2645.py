"""Tests for the three DWR-2645 / DWR-2801 findings fixed in run_digest 1.3.2 / pierre_watch 1.3.2: the dam line that is a
MultiLineString (the Pierre side), pass_end hooks that recorded neither receptors nor a reason (the hook fired before the Runner had
written the pass into run_progress.json), and the memory the watcher holds on a late pass's grid. Synthetic fixtures only; no
model, no Ollama."""
import json
import os
import shutil
import sys
import tempfile
import tracemalloc
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PIERRE = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(PIERRE, "..", ".."))
sys.path.insert(0, os.path.join(PIERRE, "tools"))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import fixture_run as FX  # noqa: E402
import pierre_watch as LW  # noqa: E402
import run_digest as RD  # noqa: E402
from strict import StrictCase, jdump, jload, slurp  # noqa: E402

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
needs_numpy = unittest.skipUnless(HAVE_NUMPY, "numpy")


class Base(StrictCase):
    def setUp(self):
        super(Base, self).setUp()
        self.root = tempfile.mkdtemp(prefix="pierre_2645_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = LW.settings()
        self.cfg.update(first_token_s=5.0, idle_s=1.0, wait_s=0.0)

    def flags(self, d, fid):
        return [f for f in d["flags"] if f["id"] == fid]


# --------------------------------------------------------------------------------------- bug 1: the dam line file
class TestDamLineContent(Base):
    def line(self, geometry):
        return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}

    def write(self, gj, name="dam_line.geojson"):
        p = os.path.join(self.root, name)
        jdump(gj, p)
        return p

    def test_what_a_dam_line_file_holds(self):
        two = [[0, 47], [0.001, 47]]
        cases = [
            (self.line({"type": "LineString", "coordinates": two}), ("LineString", 1, True)),
            (self.line({"type": "MultiLineString", "coordinates": [two]}), ("MultiLineString", 1, True)),
            (self.line({"type": "MultiLineString", "coordinates": [two, [[1, 47], [1.001, 47]]]}), ("MultiLineString", 2, True)),
            ({"type": "LineString", "coordinates": two}, ("LineString", 1, True)),                       # a bare geometry
            (self.line({"type": "MultiLineString", "coordinates": []}), (None, 0, False)),
            (self.line({"type": "Point", "coordinates": [0, 47]}), (None, 0, False)),
            ({"type": "FeatureCollection", "features": []}, (None, 0, False)),
            ({}, (None, 0, False)),
        ]
        for gj, (geom, parts, usable) in cases:
            got = RD.dam_line_info(self.write(gj))
            self.assertEqual((got["geometry"], got["parts"], got["usable"]), (geom, parts, usable), gj)

    def test_a_gpkg_or_shapefile_is_not_opened(self):
        self.assertEqual(RD.dam_line_info(os.path.join(self.root, "dam_line.gpkg"))["usable"], None)

    def test_a_multilinestring_dam_line_is_found_and_reported_with_its_parts(self):
        run, dam = FX.make_run(self.root, dam_line_at="dam")
        jdump(self.line({"type": "MultiLineString", "coordinates": [[[0, 47], [0.001, 47]], [[0.01, 47], [0.012, 47]]]}),
              os.path.join(self.root, "dam", "dam_line.geojson"))
        d = RD.build_digest(run, dam_folder=os.path.join(self.root, "dam"))
        t = d["checks"]["toe_inflow"]
        self.assertTrue(t["dam_line_found"])
        self.assertEqual((t["dam_line_geometry"], t["dam_line_parts"]), ("MultiLineString", 2))

    def test_an_empty_dam_line_file_is_not_a_dam_line(self):
        run, dam = FX.make_run(self.root, report=True, inflow_how="fallback: lowest ground within 150 m of the dam point")
        jdump({"type": "FeatureCollection", "features": []}, os.path.join(dam, "dam_line.geojson"))
        d = RD.build_digest(run, dam_folder=dam)
        t = d["checks"]["toe_inflow"]
        self.assertFalse(t["dam_line_found"])
        self.assertEqual(t["dam_line_unusable"], "no geometry")
        f = self.flags(d, "TOE_UNCHECKED")[0]
        self.assertIn("holds no line", f["detail"])

    def test_a_fallback_inflow_with_a_dam_line_file_names_the_runner_bug(self):
        run, dam = FX.make_run(self.root, report=True, dam_line_at="dam", inflow_how="fallback: lowest ground within 150 m of the dam point")
        d = RD.build_digest(run, dam_folder=os.path.join(self.root, "dam"))
        f = self.flags(d, "TOE_UNCHECKED")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "WATCH")
        self.assertIn("MultiLineString dam line was read as nothing", f[0]["detail"])


# --------------------------------------------------------------------------------------- bug 2: every pass says why
def set_progress(run, upto, bounds_for=None, complete=False):
    """run_progress.json as the Runner has written it so far: entries for passes 1..upto only; bounds_for(n) is the pass's
    own domain (a growing domain has a different one every pass)."""
    p = jload(os.path.join(run, "run_progress.json"))
    p["passes"] = [{"pass": n, "dir": "run%02d_50m" % n, "bounds": (bounds_for(n) if bounds_for else FX.BOUNDS), "cell_m": FX.CELL,
                    "wall_s": 1.0} for n in range(1, upto + 1)]
    p["complete"] = complete
    jdump(p, os.path.join(run, "run_progress.json"))


def mid_run(run):
    s = jload(os.path.join(run, "run_setup.json"))
    s["status"] = "running"
    jdump(s, os.path.join(run, "run_setup.json"))


@needs_numpy
class TestEveryPassSaysWhy(Base):
    def make(self, passes=6, upto=None):
        run, dam = FX.make_run(self.root, report=False, layout="work", progress=True, passes=passes)
        mid_run(run)
        if upto is not None:
            set_progress(run, upto)
        return run, dam, FX.write_points(self.root)

    def digest(self, run, dam, pts, n, every=2, **kw):
        cfg = dict(self.cfg, pass_receptor_every=every)
        r = LW.run_event(run, "pass_end", os.path.join(self.root, "w"), pass_no=n, pierre=False, cfg=cfg, dam_folder=dam,
                         points_path=pts, **kw)
        return r["digest"]

    def says_something(self, d):
        c = d["checks"]
        return c["receptors"] is not None or bool(c["receptors_skipped"])

    def test_dwr_2801_a_pass_the_runner_has_not_recorded_yet_has_a_reason_not_a_blank(self):
        run, dam, pts = self.make(upto=3)                    # LISFLOOD finished passes 1..6; the Runner has recorded 1..3
        d = self.digest(run, dam, pts, 4)                    # an even pass: 1.3.1 recorded neither receptors nor a reason
        c = d["checks"]
        self.assertIsNone(c["receptors"])
        self.assertIn("no georeference for this pass yet", c["receptors_skipped"])
        self.assertIn("run_progress.json", c["receptors_skipped"])
        self.assertIsNone(c.get("peaks"))

    def test_once_the_runner_has_recorded_it_the_pass_is_sampled(self):
        run, dam, pts = self.make(upto=3)
        self.assertIsNone(self.digest(run, dam, pts, 4)["checks"]["receptors"])
        set_progress(run, 4)
        d = self.digest(run, dam, pts, 4)
        self.assertIsNotNone(d["checks"]["receptors"])
        self.assertIsNone(d["checks"]["receptors_skipped"])
        self.assertIsNotNone(d["checks"]["peaks"])

    def test_a_pass_that_is_not_sampled_says_so_for_pass_1_too(self):
        run, dam, pts = self.make()
        for n in (1, 3, 5):
            self.assertIn("not sampled at this pass hook", self.digest(run, dam, pts, n)["checks"]["receptors_skipped"], n)

    def test_no_points_is_a_reason(self):
        run, dam, pts = self.make()
        cfg = dict(self.cfg, pass_receptor_every=1)
        d = LW.run_event(run, "pass_end", os.path.join(self.root, "w"), pass_no=2, pierre=False, cfg=cfg, dam_folder=dam)["digest"]
        self.assertIsNone(d["checks"]["receptors"])
        self.assertIn("no receptor points", d["checks"]["receptors_skipped"])

    def test_a_missing_result_grid_is_a_reason(self):
        run, dam, pts = self.make()
        os.remove(os.path.join(run, "model", "run02_50m", "results", "run.max"))
        d = self.digest(run, dam, pts, 2)
        self.assertIn("no results/run.max in run02_50m", d["checks"]["receptors_skipped"])

    def test_an_unreadable_grid_is_a_reason_and_still_a_flag(self):
        run, dam, pts = self.make()
        old = RD._pass_grid
        RD._pass_grid = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk gone"))
        self.addCleanup(setattr, RD, "_pass_grid", old)
        d = self.digest(run, dam, pts, 2)
        self.assertIn("disk gone", d["checks"]["receptors_skipped"])
        self.assertTrue(self.flags(d, "NO_RUN_FILES"))

    def test_every_hook_of_every_run_shape_carries_receptors_or_a_reason(self):
        for every in (0, 1, 2, 3):
            for upto in (0, 2, 6):
                shutil.rmtree(self.root)
                os.makedirs(self.root)
                run, dam, pts = self.make(upto=upto)
                for n in range(1, 7):
                    d = self.digest(run, dam, pts, n, every=every)
                    self.assertTrue(self.says_something(d), (every, upto, n))
                end = LW.run_event(run, "run_end", os.path.join(self.root, "w"), pierre=False, cfg=self.cfg, dam_folder=dam)["digest"]
                self.assertTrue(self.says_something(end), (every, upto, "run_end"))

    def test_the_memory_guard_skips_the_read_and_says_why(self):
        run, dam, pts = self.make()
        old = os.environ.get("PIERRE_WATCH_MIN_FREE_MB")
        os.environ["PIERRE_WATCH_MIN_FREE_MB"] = "100000000"
        self.addCleanup(lambda: os.environ.pop("PIERRE_WATCH_MIN_FREE_MB", None) if old is None
                        else os.environ.__setitem__("PIERRE_WATCH_MIN_FREE_MB", old))
        if RD.mem_available_mb() is None:
            self.skipTest("no /proc/meminfo")
        d = self.digest(run, dam, pts, 2)
        self.assertIsNone(d["checks"]["receptors"])
        self.assertIn("PIERRE_WATCH_MIN_FREE_MB", d["checks"]["receptors_skipped"])
        # the final outputs at run_end are not guarded
        end = LW.run_event(run, "run_end", os.path.join(self.root, "w"), pierre=False, cfg=self.cfg, dam_folder=dam)["digest"]
        self.assertTrue(self.says_something(end))


@needs_numpy
class TestDetectorWaitsForTheRunner(Base):
    def setUp(self):
        super(TestDetectorWaitsForTheRunner, self).setUp()
        self.run, self.dam = FX.make_run(self.root, report=False, layout="work", progress=True, passes=6)
        mid_run(self.run)
        self.det = LW.EventDetector(record_grace_s=120.0)

    def passes(self, evs):
        return [e["pass"] for e in evs if e["event"] == "pass_end"]

    def test_a_finished_pass_waits_until_the_runner_has_recorded_it(self):
        set_progress(self.run, 2)
        st = {}
        self.assertEqual(self.passes(self.det.scan(self.run, st)), [1, 2])
        self.assertEqual(self.passes(self.det.scan(self.run, st)), [])           # 3..6 wait; nothing fires twice
        set_progress(self.run, 3)
        self.assertEqual(self.passes(self.det.scan(self.run, st)), [3])
        set_progress(self.run, 6)
        self.assertEqual(self.passes(self.det.scan(self.run, st)), [4, 5, 6])

    def test_the_wait_has_a_cap_for_a_runner_that_never_records_it(self):
        set_progress(self.run, 2)
        st = {}
        self.det.scan(self.run, st)
        later = max(os.path.getmtime(os.path.join(d, "lisflood.log")) for d in RD._pass_dirs(self.run)) + 121.0
        self.assertEqual(self.passes(self.det.scan(self.run, st, now=later)), [3, 4, 5, 6])

    def test_an_older_runner_without_run_progress_json_is_not_delayed(self):
        run, _dam = FX.make_run(os.path.join(self.root, "old"), report=False, layout="work", progress=False, passes=3)
        self.assertEqual(self.passes(self.det.scan(run, {})), [1, 2, 3])

    def test_a_finished_run_is_not_delayed(self):
        set_progress(self.run, 2, complete=True)
        self.assertEqual(self.passes(self.det.scan(self.run, {})), [1, 2, 3, 4, 5, 6])

    def test_the_grace_is_a_setting(self):
        os.environ["PIERRE_WATCH_RECORD_GRACE_S"] = "7"
        self.addCleanup(os.environ.pop, "PIERRE_WATCH_RECORD_GRACE_S", None)
        self.assertEqual(LW.settings()["record_grace_s"], 7.0)
        self.assertEqual(LW.settings()["pass_receptor_every"], 2)


@needs_numpy
class TestTheGrowthPath(Base):
    """The Absaraka shape: a domain that grows pass after pass, LISFLOOD-FP finishing faster than the Runner records, the watcher
    scanning in between. Every pass must come out with receptors or a reason; every even pass must be sampled."""

    def test_nine_growing_passes_with_a_lagging_progress_file(self):
        run, dam = FX.make_run(self.root, report=False, layout="work", progress=True, passes=9)
        mid_run(run)
        pts = FX.write_points(self.root)
        # a growing domain has its own origin every pass (here: moved out by up to two cells), so every pass's georeference is its own
        grow = lambda n: [-FX.CELL * (n % 3), -FX.CELL * (n % 2), FX.BOUNDS[2], FX.BOUNDS[3]]       # noqa: E731
        det, st, out = LW.EventDetector(record_grace_s=120.0), {}, {}
        cfg = dict(self.cfg, pass_receptor_every=2)
        recorded = 0
        for scan in range(1, 30):
            if scan % 3 == 0 and recorded < 9:                               # the Runner records a pass every third scan
                recorded += 1
            set_progress(run, recorded, bounds_for=grow)
            for e in det.scan(run, st):
                if e["event"] == "pass_end":
                    r = LW.run_event(run, "pass_end", os.path.join(self.root, "w"), pass_no=e["pass"], pierre=False, cfg=cfg,
                                     dam_folder=dam, points_path=pts)
                    out[e["pass"]] = r["digest"]["checks"]
        self.assertEqual(sorted(out), list(range(1, 10)))
        for n, c in sorted(out.items()):
            self.assertTrue(c["receptors"] is not None or c["receptors_skipped"], n)
            if n % 2 == 0:
                self.assertIsNotNone(c["receptors"], "even pass %d was not sampled: %s" % (n, c["receptors_skipped"]))
                self.assertEqual(c["receptors"]["sampled"] + c["receptors"]["outside"], 4)
            else:
                self.assertIsNone(c["receptors"], n)
                self.assertIn("not sampled", c["receptors_skipped"])

    def test_a_hook_replayed_gives_the_same_receptors_the_grid_is_not_shared(self):
        run, dam = FX.make_run(self.root, report=False, layout="work", progress=True, passes=2)
        mid_run(run)
        pts = FX.write_points(self.root)
        a = RD.build_digest(run, "pass_end", dam_folder=dam, upto_pass=2, points_path=pts)["checks"]["receptors"]
        b = RD.build_digest(run, "pass_end", dam_folder=dam, upto_pass=2, points_path=pts)["checks"]["receptors"]
        self.assertEqual(a, b)
        self.assertTrue(a["nodata_next_to_wet"])

    def test_the_watch_log_line_names_the_reason(self):
        run, dam = FX.make_run(self.root, report=False, layout="work", progress=True, passes=2)
        mid_run(run)
        lines = []
        LW.watch(run, os.path.join(self.root, "w"), pierre=False, once=True, cfg=dict(self.cfg, pass_receptor_every=2),
                 log=lines.append, dam_folder=dam, points_path=FX.write_points(self.root))
        p1 = [l for l in lines if "pass_end (pass 1)" in l][0]
        p2 = [l for l in lines if "pass_end (pass 2)" in l][0]
        self.assertIn("receptors skipped: receptors not sampled at this pass hook", p1)
        self.assertNotIn("receptors skipped", p2)


# --------------------------------------------------------------------------------------- bug 3: memory
def write_grid(path, arr, nodata=-9999.0, cell=50.0):
    head = "ncols %d\nnrows %d\nxllcorner 0.0\nyllcorner 0.0\ncellsize %.1f\nNODATA_value %.1f\n" % (
        arr.shape[1], arr.shape[0], cell, nodata)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(head)
        np.savetxt(f, np.where(np.isnan(arr), nodata, arr), fmt="%.3f", delimiter="\t")


@needs_numpy
class TestMemory(Base):
    def grid(self, n=700):
        rng = np.random.default_rng(7)
        a = np.round(rng.uniform(0, 3, (n, n)), 3)
        a[rng.uniform(size=a.shape) < 0.1] = np.nan
        a[0, 5] = a[-1, 7] = a[9, 0] = a[11, -1] = np.nan                   # NoData on every edge
        return a

    def test_the_streamed_edges_equal_the_whole_grid_edges(self):
        a = self.grid()
        p = os.path.join(self.root, "run.max")
        write_grid(p, a)
        want = RD.edge_depths_ft(RD.read_asc(p)[0])
        self.assertEqual(RD.read_asc_edges(p), want)
        self.assertEqual(RD.read_asc_edges(p), want)                            # the cached read answers the same

    def test_an_all_nodata_edge_is_zero_and_a_one_row_grid_works(self):
        p = os.path.join(self.root, "a.asc")
        write_grid(p, np.full((3, 4), np.nan))
        self.assertEqual(RD.read_asc_edges(p), {"N": 0.0, "S": 0.0, "W": 0.0, "E": 0.0})
        q = os.path.join(self.root, "b.asc")
        write_grid(q, np.array([[1.0, 2.0, 3.0]]))
        self.assertEqual(RD.read_asc_edges(q), RD.edge_depths_ft(RD.read_asc(q)[0]))

    def test_the_edge_read_holds_a_row_not_the_grid(self):
        a = self.grid(1200)                                                      # 1.44 M cells, 11.5 MB as float64
        p = os.path.join(self.root, "run.max")
        write_grid(p, a)
        RD._EDGE_CACHE.clear()
        tracemalloc.start()
        RD.read_asc_edges(p)
        _c, peak_edges = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        tracemalloc.start()
        RD.edge_depths_ft(RD.read_asc(p)[0])
        _c, peak_whole = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print("\n[mem] edge read peak %.2f MB vs whole-grid read %.1f MB (1200 x 1200)" % (peak_edges / 1e6, peak_whole / 1e6))
        self.assertLess(peak_edges, 1.5e6)
        self.assertGreater(peak_whole, 8 * peak_edges)

    def test_a_big_grid_is_read_as_float32_and_a_small_one_stays_float64(self):
        p = os.path.join(self.root, "run.max")
        write_grid(p, self.grid(60))
        self.assertEqual(RD.read_asc(p)[0].dtype, np.float64)
        old = RD.BIG_GRID_CELLS
        RD.BIG_GRID_CELLS = 100
        self.addCleanup(setattr, RD, "BIG_GRID_CELLS", old)
        a, _h = RD.read_asc(p)
        self.assertEqual(a.dtype, np.float32)
        self.assertEqual(int(np.isnan(a).sum()), int(np.isnan(self.grid(60)).sum()))        # NoData still NaN
        np.testing.assert_allclose(a, self.grid(60), rtol=1e-6, equal_nan=True)

    def test_the_pass_grid_matches_the_old_formula_and_the_inputs_are_not_kept(self):
        wd = os.path.join(self.root, "run01_50m")
        depth, dem = self.grid(40), np.full((40, 40), 100.0)
        dem[3, 3] = dem[10, 11] = np.nan
        depth[10, 11] = 1.0                                                      # a DEM hole under water stays NoData
        write_grid(os.path.join(wd, "results", "run.max"), depth)
        write_grid(os.path.join(wd, "results", "run.dem"), dem)
        g = RD._pass_grid(wd, ".max", [0.0, 0.0, 2000.0, 2000.0], 1.0 / RD.FT)
        a, _ = RD.read_asc(os.path.join(wd, "results", "run.max"))
        d, _ = RD.read_asc(os.path.join(wd, "results", "run.dem"))
        want = np.where(np.isnan(d), np.nan, np.where(np.isnan(a), 0.0, a)) * (1.0 / RD.FT)
        np.testing.assert_array_equal(g.data, want)

    def test_the_peaks_equal_the_old_where_formula(self):
        run, dam = FX.make_run(self.root, report=False, layout="work", progress=True, passes=2)
        mid_run(run)
        d = RD.build_digest(run, "pass_end", dam_folder=dam, upto_pass=2)
        pk = d["checks"]["peaks"]
        g = RD._pass_grid(os.path.join(run, "model", "run02_50m"), ".max", FX.BOUNDS, 1.0 / RD.FT)
        wet = np.isfinite(g.data) & (g.data >= RD.THRESHOLDS["wet_ft"])
        self.assertEqual(pk["peak_depth_ft"], round(float(np.nanmax(np.where(wet, g.data, np.nan))), 2))
        self.assertEqual(pk["wet_cells"], int(wet.sum()))

    def test_pass_records_cache_the_edges_so_an_old_pass_is_not_reread_at_every_hook(self):
        run, dam = FX.make_run(self.root, report=False, layout="work", progress=True, passes=4)
        mid_run(run)
        calls = []
        old = RD.read_asc_edges.__wrapped__ if hasattr(RD.read_asc_edges, "__wrapped__") else None       # noqa: F841
        real = RD.read_asc

        def counting(path):
            calls.append(path)
            return real(path)
        RD.read_asc = counting
        self.addCleanup(setattr, RD, "read_asc", real)
        RD._EDGE_CACHE.clear()
        for n in (1, 2, 3, 4):
            RD.build_digest(run, "pass_end", dam_folder=dam, upto_pass=n, sample_receptors=False)
        edge_reads = [c for c in calls if c.endswith("run.max")]
        # the edges never go through read_asc; the pass grid (peaks) is read once per hook, one grid, not one per earlier pass
        self.assertEqual(len(edge_reads), 4)
        self.assertEqual(len(RD._EDGE_CACHE), 4)


# --------------------------------------------------------------------------------------- the Runner's widened toe band
WIDE_HOW = ("lowest ground at the downstream toe: 5-37 m downstream of the dam line along its full length (2 m DEM), 36 m from the "
            "line, 24.5 ft below the top of dam (band widened from 27 m: the ground nearer is the dam's face, less than 75 % of the "
            "dam height below its top)")


class TestWidenedToeBand(Base):
    """DWR-2645 (Pheasant Lake): H 29.6 ft, 2:1, band 5-27.1 m; the Runner widened it to 37 m (the nearer ground was the dam's face)
    and put the inflow 36 m from the line. 1.3.2 called that TOE_INFLOW PROBLEM."""

    def digest(self, dist=36.0, fields=None, how=None):
        run, dam = FX.make_run(self.root, height_ft=29.6, streambed_ft=1470.4, ds_slope=2.0, toe_distance=dist, toe_outer=27.0662,
                               inflow_how=how)
        if fields is not None:
            p = os.path.join(run, "run_report.json")
            r = jload(p)
            r["inflow"]["toe_band"].update(fields)
            jdump(r, p)
        return RD.build_digest(run, dam_folder=dam)

    WIDE = {"effective_inner_m": 5.0, "effective_outer_m": 37.0, "original_outer_m": 27.0662, "widened": True,
            "widening_reason": "the ground nearer is the dam's face, less than 75 % of the dam height below its top"}

    def test_the_old_report_without_the_fields_is_judged_as_before(self):
        d = self.digest(36.0)
        self.assertEqual(len(self.flags(d, "TOE_INFLOW")), 1)
        self.assertEqual(self.flags(d, "TOE_BAND_WIDENED"), [])
        self.assertEqual(d["verdict"], "PROBLEM")

    def test_an_inflow_inside_the_widened_band_is_an_info_note_naming_the_reason(self):
        d = self.digest(36.0, self.WIDE)
        self.assertEqual(self.flags(d, "TOE_INFLOW"), [])
        f = self.flags(d, "TOE_BAND_WIDENED")
        self.assertEqual([x["severity"] for x in f], ["INFO"])
        self.assertIn("5-37 m", f[0]["title"])
        self.assertIn("dam's face", f[0]["detail"])
        self.assertIn("run_report toe_band", f[0]["detail"])
        self.assertNotEqual(d["verdict"], "PROBLEM")

    def test_an_inflow_outside_the_effective_band_is_still_a_problem(self):
        d = self.digest(45.0, self.WIDE)
        f = self.flags(d, "TOE_INFLOW")
        self.assertEqual([x["severity"] for x in f], ["PROBLEM"])
        self.assertIn("widened it to 5-37 m", f[0]["title"])
        self.assertEqual(self.flags(d, "TOE_BAND_WIDENED"), [])
        self.assertEqual(d["verdict"], "PROBLEM")

    def test_too_close_to_the_line_is_a_problem_in_a_widened_band_too(self):
        self.assertEqual(len(self.flags(self.digest(2.0, self.WIDE), "TOE_INFLOW")), 1)

    def test_a_widened_flag_that_is_false_does_not_excuse_an_inflow_outside_the_nominal_band(self):
        d = self.digest(36.0, dict(self.WIDE, widened=False))
        self.assertEqual(len(self.flags(d, "TOE_INFLOW")), 1)

    def test_an_inflow_inside_the_nominal_band_needs_no_note_even_with_a_widened_band(self):
        d = self.digest(20.0, self.WIDE)
        self.assertEqual(self.flags(d, "TOE_INFLOW"), [])
        self.assertEqual(self.flags(d, "TOE_BAND_WIDENED"), [])

    def test_a_report_with_only_the_runner_text_is_read_from_the_text(self):
        d = self.digest(36.0, how=WIDE_HOW)                      # the 2645 report of 1edfde5 (no fields, the text says it all)
        self.assertEqual(self.flags(d, "TOE_INFLOW"), [])
        f = self.flags(d, "TOE_BAND_WIDENED")
        self.assertEqual(len(f), 1)
        self.assertIn("the Runner's inflow text", f[0]["detail"])
        self.assertIn("dam's face", f[0]["detail"])
        d = self.digest(45.0, how=WIDE_HOW.replace("36 m from", "45 m from"))
        self.assertEqual(len(self.flags(d, "TOE_INFLOW")), 1)

    def test_a_toe_band_without_a_widening_still_checks_the_nominal_band(self):
        plain = {"effective_inner_m": 5.0, "effective_outer_m": 27.0662, "original_outer_m": 27.0662, "widened": False,
                 "widening_reason": None}
        self.assertEqual(self.flags(self.digest(20.0, plain), "TOE_INFLOW"), [])
        self.assertEqual(len(self.flags(self.digest(36.0, plain), "TOE_INFLOW")), 1)

    def test_the_new_flag_is_known_and_documented(self):
        self.assertIn("TOE_BAND_WIDENED", RD.KNOWN_FLAG_IDS)
        t = slurp(os.path.join(PIERRE, "knowledge", "WATCHER-DIGEST.md"))
        self.assertIn("TOE_BAND_WIDENED", t)
        self.assertIn("effective_outer_m", t)


class TestKeepAlive(Base):
    def test_the_watcher_reports_its_own_memory(self):
        rss, peak = LW.own_rss_mb()
        if rss is None:
            self.skipTest("no /proc")
        self.assertGreater(rss, 1.0)
        self.assertGreaterEqual(peak, rss)


    def test_the_model_is_not_kept_for_30_minutes_any_more(self):
        p = LW.chat_payload([{"role": "user", "content": "x"}], LW.settings())
        self.assertEqual(p["keep_alive"], "2m")
        os.environ["PIERRE_WATCH_KEEP_ALIVE"] = "10s"
        self.addCleanup(os.environ.pop, "PIERRE_WATCH_KEEP_ALIVE", None)
        self.assertEqual(LW.chat_payload([], LW.settings())["keep_alive"], "10s")

    def test_versions_and_docs(self):
        self.assertEqual((RD.VERSION, LW.VERSION), ("1.3.4", "1.3.4"))
        t = slurp(os.path.join(PIERRE, "knowledge", "WATCHER-DIGEST.md"))
        for needle in ("PIERRE_WATCH_RECORD_GRACE_S", "PIERRE_WATCH_MIN_FREE_MB", "PIERRE_WATCH_KEEP_ALIVE", "receptors_skipped"):
            self.assertIn(needle, t, needle)


if __name__ == "__main__":
    unittest.main()
