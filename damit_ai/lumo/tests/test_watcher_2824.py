"""Tests for the DWR-2824 retest bugs fixed in run_digest 1.3.0 / lumo_watch 1.3.0 (Runner 0.3.1's run_progress.json):
the explanation waits for the Runner's whole pipeline (not a quiet gap), the dam line is found where the suite keeps it, and
pass hooks flag receptors from the pass's own georeference. Synthetic fixtures only; no model, no Ollama, no real run."""
import json
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
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
needs_numpy = unittest.skipUnless(HAVE_NUMPY, "numpy")


class Base(StrictCase):
    def setUp(self):
        super(Base, self).setUp()
        self.root = tempfile.mkdtemp(prefix="lumo_2824_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = LW.settings()
        self.cfg.update(first_token_s=5.0, idle_s=1.0, wait_s=0.0)

    def flags(self, d, fid):
        return [f for f in d["flags"] if f["id"] == fid]

    def set_status(self, run, status):
        s = jload(os.path.join(run, "run_setup.json"))
        s["status"] = status
        jdump(s, os.path.join(run, "run_setup.json"))

    def midrun(self, **kw):
        """A run the Runner is still working on: passes on disk, no run_report.json, status running."""
        kw.setdefault("progress", True)
        run, dam = FX.make_run(self.root, report=False, layout="work", **kw)
        self.set_status(run, "running")
        return run, dam


# ------------------------------------------------------------------------------------------- item 2: the idle gate
@needs_numpy
class TestGateWaitsForTheWholeRun(Base):
    def test_defaults_and_environment(self):
        self.assertEqual(LW.settings()["stale_s"], RD.THRESHOLDS["stall_s"])
        os.environ["LUMO_WATCH_STALE_S"] = "60"
        self.addCleanup(os.environ.pop, "LUMO_WATCH_STALE_S", None)
        self.assertEqual(LW.settings()["stale_s"], 60.0)

    def test_two_seconds_after_pass_6_is_not_idle(self):
        """The retest: the explain started 2 s after pass 6 and ran through passes 7-8."""
        run, _dam = self.midrun(passes=6)
        now = time.time()
        for d in RD._pass_dirs(run):
            os.utime(os.path.join(d, "lisflood.log"), (now - 2, now - 2))
        os.utime(os.path.join(run, "run_progress.json"), (now - 2, now - 2))
        for mode in ("idle", "end"):
            ok, why = LW.explain_gate(run, dict(self.cfg, explain=mode, idle_gap_s=0.0), now=now, proc=False)
            self.assertFalse(ok, mode)
            self.assertIn("run has not finished", why)
        st = LW.engine_state(run, self.cfg, now=now, proc=False)
        self.assertEqual((st["idle"], st["complete"]), (False, False))

    def test_a_quiet_run_is_not_idle_until_it_is_stale(self):
        run, _dam = self.midrun()
        now = time.time()
        self.assertFalse(LW.engine_state(run, self.cfg, now=now + 300, proc=False)["idle"])
        self.assertFalse(LW.engine_state(run, self.cfg, now=now + 800, proc=False)["idle"])

    def test_each_completion_marker_makes_it_idle(self):
        # run_progress.json complete, nothing else
        run, _dam = self.midrun(progress_complete=True)
        st = LW.engine_state(run, self.cfg, proc=False)
        self.assertTrue(st["idle"] and st["complete"])
        self.assertIn("run_progress.json", st["reason"])
        self.assertTrue(LW.explain_gate(run, dict(self.cfg, explain="idle"), proc=False)[0])
        # run_report.json (a run from a Runner without run_progress.json)
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        run, _dam = FX.make_run(self.root, layout="work")
        self.set_status(run, "running")
        st = LW.engine_state(run, self.cfg, proc=False)
        self.assertTrue(st["idle"])
        self.assertIn("run_report.json", st["reason"])
        # status finished without a report, and status failed
        os.remove(os.path.join(run, "run_report.json"))
        for status, ok in (("running", False), ("finished", True), ("failed", True)):
            self.set_status(run, status)
            self.assertEqual(LW.engine_state(run, self.cfg, proc=False)["idle"], ok, status)

    def test_a_running_lisflood_process_still_blocks_a_finished_run(self):
        run, _dam = self.midrun(progress_complete=True)
        st = LW.engine_state(run, self.cfg, proc=True)
        self.assertFalse(st["idle"])
        self.assertIn("lisflood process", st["reason"])

    def test_a_dead_runner_does_not_block_lumo_forever(self):
        run, _dam = self.midrun()
        now = time.time() + 5000
        st = LW.engine_state(run, self.cfg, now=now, proc=False)
        self.assertTrue(st["idle"])
        self.assertFalse(st["complete"])
        self.assertTrue(st["abandoned"])
        self.assertIn("did not finish", st["reason"])
        self.assertFalse(LW.engine_state(run, self.cfg, now=now, proc=True)["idle"])             # still LISFLOOD: wait
        self.assertFalse(LW.engine_state(run, dict(self.cfg, stale_s=0), now=now, proc=False)["idle"])     # 0 = never
        self.assertTrue(LW.explain_gate(run, dict(self.cfg, explain="idle"), now=now, proc=False)[0])

    def test_pass_hooks_only_queue_mid_run(self):
        run, dam = self.midrun()
        spawned = []
        out = os.path.join(self.root, "w")
        for n in (1, 2, 3):
            r = LW.run_event(run, "pass_end", out, pass_no=n, lumo=True, cfg=self.cfg, dam_folder=dam,
                             spawn=lambda jp, c: spawned.append(jp))
            self.assertEqual(r["lumo"]["status"], "queued", n)
            self.assertIn("run has not finished", r["lumo"]["error"])
            self.assertTrue(os.path.exists(r["digest_path"]))                    # the digest is written at once
        self.assertEqual(spawned, [])

    def test_watch_starts_nothing_while_the_runner_works_and_one_explain_when_it_is_done(self):
        run, dam = FX.make_run(self.root, layout="work", progress=True, progress_complete=True)
        report = os.path.join(run, "run_report.json")
        held = report + ".held"
        os.rename(report, held)
        prog = jload(os.path.join(run, "run_progress.json"))
        jdump(dict(prog, complete=False), os.path.join(run, "run_progress.json"))
        self.set_status(run, "running")
        spawns, sleeps = [], []

        def sleep(_s):
            sleeps.append(1)
            if len(sleeps) == 3:                                               # the Runner finishes during the third poll
                self.assertEqual(spawns, [], "nothing may start while the Runner is working")
                os.rename(held, report)
                jdump(dict(prog, complete=True), os.path.join(run, "run_progress.json"))
                self.set_status(run, "finished")
        res = LW.watch(run, os.path.join(self.root, "w"), poll_s=0, until="before_hazard", lumo=True, cfg=self.cfg,
                       max_wait_s=30, log=lambda *a: None, sleep=sleep, dam_folder=dam,
                       spawn=lambda jp, c: spawns.append(jp))
        self.assertEqual([r["event"] for r in res][:3], ["pass_end", "pass_end", "pass_end"])
        self.assertIn("run_end", [r["event"] for r in res])
        self.assertGreaterEqual(len(sleeps), 3)
        self.assertEqual(len(spawns), 1)                                       # one inference, for the newest event
        self.assertTrue(spawns[0].endswith("digest_before_hazard.json"))

    def test_the_digest_says_whether_the_run_is_complete(self):
        run, dam = self.midrun()
        d = RD.build_digest(run, "pass_end", dam_folder=dam, upto_pass=2)
        self.assertFalse(d["checks"]["run"]["complete"])
        run2, dam2 = FX.make_run(os.path.join(self.root, "b"), layout="work", progress=True, progress_complete=True)
        d2 = RD.build_digest(run2, "run_end", dam_folder=dam2)
        self.assertTrue(d2["checks"]["run"]["complete"])
        self.assertIn("run_progress.json", d2["checks"]["run"]["complete_by"])


# ------------------------------------------------------------------------------------ item 3: the dam line search
@needs_numpy
class TestDamLineSearch(Base):
    def toe_flag(self, run, dam):
        d = RD.build_digest(run, "run_end", dam_folder=dam)
        return d, [f["id"] for f in d["flags"] if f["id"] in ("TOE_SOURCE_RUN_REPORT", "TOE_UNCHECKED")]

    def test_the_retest_layout_work_inputs_is_found(self):
        run, dam = FX.make_run(self.root, layout="work", dam_line_at="work/inputs")
        p = RD.find_dam_line(dam, run)
        self.assertEqual(p, os.path.join(self.root, "work", "inputs", "dam_line.geojson"))
        d, toe = self.toe_flag(run, dam)
        self.assertEqual(toe, [])                                  # no "toe from run_report, no dam_line" note
        self.assertTrue(d["checks"]["toe_inflow"]["dam_line_found"])
        self.assertEqual(d["checks"]["toe_inflow"]["dam_line_path"], p)
        self.assertEqual(d["checks"]["toe_inflow"]["distance_source"], "run_report")

    def test_not_found_anywhere_still_says_so(self):
        run, dam = FX.make_run(self.root, layout="work")
        self.assertIsNone(RD.find_dam_line(dam, run))
        d, toe = self.toe_flag(run, dam)
        self.assertEqual(toe, ["TOE_SOURCE_RUN_REPORT"])
        self.assertFalse(d["checks"]["toe_inflow"]["dam_line_found"])

    def test_every_known_place(self):
        places = ["work/inputs", "work/dams/TST00001", "work/dams/TST00001/inputs", "work/handoff/TST00001",
                  "work/runs/TST00001/TST00001/run_20260101_000000", "work/runs/TST00001/TST00001/run_20260101_000000/inputs"]
        for i, place in enumerate(places):
            root = os.path.join(self.root, "case%d" % i)
            run, dam = FX.make_run(root, layout="work", dam_line_at=place)
            self.assertEqual(RD.find_dam_line(dam, run, dam_id="TST00001"), os.path.join(root, place, "dam_line.geojson"), place)

    def test_the_folder_of_a_setup_input_is_searched_and_a_named_path_wins_nothing_else(self):
        run, dam = FX.make_run(self.root, layout="work", dam_line_at="elsewhere")
        self.assertIsNone(RD.find_dam_line(dam, run))
        s = jload(os.path.join(run, "run_setup.json"))
        s["inputs"] = {"terrain": os.path.join(self.root, "elsewhere", "terrain.tif"), "hydrograph_csv": None}
        jdump(s, os.path.join(run, "run_setup.json"))
        self.assertEqual(RD.find_dam_line(dam, run, s), os.path.join(self.root, "elsewhere", "dam_line.geojson"))
        d, toe = self.toe_flag(run, dam)
        self.assertEqual(toe, [])

    def test_the_linestring_copy_counts(self):
        run, dam = FX.make_run(self.root, layout="work")
        p = os.path.join(self.root, "work", "inputs", "dam_line_linestring.geojson")
        os.makedirs(os.path.dirname(p))
        with open(p, "w") as f:
            f.write("{}")
        self.assertEqual(RD.find_dam_line(dam, run), p)

    def test_another_dams_handoff_is_not_used(self):
        run, dam = FX.make_run(self.root, layout="work", dam_line_at="work/handoff/OTHER00002")
        self.assertIsNone(RD.find_dam_line(dam, run, dam_id="TST00001"))

    def test_the_old_places_still_work(self):
        run, dam = FX.make_run(self.root)                                   # flat layout
        os.makedirs(os.path.join(dam, "inputs"))
        with open(os.path.join(dam, "inputs", "dam_line.geojson"), "w") as f:
            json.dump(FX.DAM_LINE_GEOJSON, f)
        self.assertTrue(RD._dam_line_found(dam, run))
        self.assertFalse(RD._dam_line_found(None, None))


# ------------------------------------------------------------------------------- item 4: receptors at the pass hooks
@needs_numpy
class TestPassHooksFlagReceptors(Base):
    def rows(self):
        return FX.receptor_rows() + [("900000005", ) + FX.centre(*FX.DRY_ZERO_BESIDE_DEEP)]

    def ids(self, d):
        return {fid: sorted((self.flags(d, fid) or [{"data": {"ids": []}}])[0]["data"]["ids"])
                for fid in ("RECEPTOR_NODATA", "RECEPTOR_DRY_NEXT_TO_WET")}

    WANT = {"RECEPTOR_NODATA": ["900000001", "900000005"], "RECEPTOR_DRY_NEXT_TO_WET": ["900000003"]}

    def test_a_midrun_pass_hook_flags_receptors_with_no_run_report(self):
        run, dam = self.midrun()
        self.assertFalse(os.path.exists(os.path.join(run, "run_report.json")))
        pts = FX.write_points(self.root, self.rows())
        for n in (1, 2, 3):
            d = RD.build_digest(run, "pass_end", dam_folder=dam, points_path=pts, upto_pass=n)
            self.assertEqual(self.ids(d), self.WANT, "pass hook %d" % n)
            self.assertIn("in progress", self.flags(d, "RECEPTOR_NODATA")[0]["data"]["grid_source"])
            self.assertIsNotNone(d["checks"]["receptors"])
            self.assertEqual(d["checks"]["receptors"]["sampled"], len(self.rows()))

    def test_without_a_georeference_a_mid_run_hook_still_cannot_flag_them(self):
        run, dam = self.midrun(progress=False)                 # an older Runner: no run_report.json, no run_progress.json
        pts = FX.write_points(self.root, self.rows())
        d = RD.build_digest(run, "pass_end", dam_folder=dam, points_path=pts, upto_pass=2)
        self.assertEqual(self.ids(d), {"RECEPTOR_NODATA": [], "RECEPTOR_DRY_NEXT_TO_WET": []})
        self.assertIsNone(d["checks"]["receptors"])

    def test_the_hook_and_run_end_agree(self):
        run, dam = FX.make_run(self.root, layout="work", progress=True, progress_complete=True)
        pts = FX.write_points(self.root, self.rows())
        end = RD.build_digest(run, "run_end", dam_folder=dam, points_path=pts)
        self.assertEqual(self.ids(end), self.WANT)
        for n in (1, 2, 3):
            self.assertEqual(self.ids(RD.build_digest(run, "pass_end", dam_folder=dam, points_path=pts, upto_pass=n)), self.WANT)

    def test_the_structure_layer_is_read_in_the_crs_the_progress_file_gives(self):
        run, dam = self.midrun()
        layer = os.path.join(self.root, "structures.gpkg")
        with open(layer, "w") as f:
            f.write("x")
        seen = []

        def fake(path, wkt, **k):
            seen.append((path, wkt))
            return self.rows()
        old = RD.load_points_ogr
        RD.load_points_ogr = fake
        self.addCleanup(setattr, RD, "load_points_ogr", old)
        d = RD.build_digest(run, "pass_end", dam_folder=dam, structures_path=layer, upto_pass=2)
        self.assertEqual(seen, [(layer, FX.PROGRESS_WKT)])
        self.assertEqual(self.ids(d), self.WANT)

    def test_each_pass_uses_its_own_bounds(self):
        run, dam = self.midrun()
        prog = jload(os.path.join(run, "run_progress.json"))
        other = [b + 100.0 for b in FX.BOUNDS]
        prog["passes"][1]["bounds"] = other
        jdump(prog, os.path.join(run, "run_progress.json"))
        pts = FX.write_points(self.root, self.rows())
        seen = []
        old = RD._pass_grid
        RD._pass_grid = lambda pdir, ext, bounds, scale=1.0: (seen.append((os.path.basename(pdir), ext, list(bounds))),
                                                             old(pdir, ext, bounds, scale))[1]
        self.addCleanup(setattr, RD, "_pass_grid", old)
        RD.build_digest(run, "pass_end", dam_folder=dam, points_path=pts, upto_pass=1)
        RD.build_digest(run, "pass_end", dam_folder=dam, points_path=pts, upto_pass=2)
        self.assertEqual([s[2] for s in seen if s[1] == ".max"], [list(FX.BOUNDS), other])

    def test_a_pass_missing_from_the_progress_file_is_not_sampled_on_another_domain(self):
        run, dam = self.midrun()
        prog = jload(os.path.join(run, "run_progress.json"))
        prog["passes"] = prog["passes"][:1]
        jdump(prog, os.path.join(run, "run_progress.json"))
        pts = FX.write_points(self.root, self.rows())
        d = RD.build_digest(run, "pass_end", dam_folder=dam, points_path=pts, upto_pass=3)
        self.assertIsNone(d["checks"]["receptors"])


@needs_numpy
class TestHazardNoteAboutAnEmptyLayer(Base):
    """Item 4 on the watcher side: Hazard 0.2.2's INFO layer_none_scored is not a thing to review; no_layer still is."""

    def hazard_digest(self, code, level):
        run, dam = FX.make_run(self.root, hazard=True)
        path = os.path.join(dam, "classify", "damit_hazard_report.json")
        rep = jload(path)
        rep["flags"] = [{"level": level, "code": code, "message": "m", "method": "M9a", "receptors": []}]
        jdump(rep, path)
        return RD.build_digest(run, "run_end", dam_folder=dam)

    def test_layer_none_scored_does_not_raise_hazard_review(self):
        d = self.hazard_digest("layer_none_scored", "info")
        self.assertFalse([f for f in d["flags"] if f["id"] == "HAZARD_REVIEW"])
        self.assertEqual(d["checks"]["hazard"]["review_counts"], {})

    def test_no_layer_still_does(self):
        d = self.hazard_digest("no_layer", "warning")
        self.assertEqual(len([f for f in d["flags"] if f["id"] == "HAZARD_REVIEW"]), 1)


class TestProgressHelpers(Base):
    def test_load_and_match(self):
        os.makedirs(os.path.join(self.root, "r"))
        self.assertEqual(RD.load_progress(os.path.join(self.root, "r")), {})
        jdump({"passes": [{"dir": "run02_50m", "bounds": [1, 2, 3, 4]}]}, os.path.join(self.root, "r", "run_progress.json"))
        prog = RD.load_progress(os.path.join(self.root, "r"))
        self.assertEqual(RD.progress_pass(prog, "/x/model/run02_50m")["bounds"], [1, 2, 3, 4])
        self.assertEqual(RD.progress_pass(prog, "/x/model/run03_50m"), {})
        self.assertEqual(RD.run_complete(os.path.join(self.root, "r")), (False, None))

    def test_a_later_loop_reusing_a_pass_folder_name_wins(self):
        prog = {"passes": [{"dir": "run01_10m", "bounds": [0, 0, 1, 1]}, {"dir": "run02_10m", "bounds": [5, 5, 6, 6]},
                           {"dir": "run01_10m", "bounds": [9, 9, 10, 10]}]}
        self.assertEqual(RD.progress_pass(prog, "/m/run01_10m")["bounds"], [9, 9, 10, 10])
        self.assertEqual(RD.progress_pass(prog, "/m/run02_10m")["bounds"], [5, 5, 6, 6])

    def test_a_broken_progress_file_is_ignored(self):
        os.makedirs(os.path.join(self.root, "r"))
        with open(os.path.join(self.root, "r", "run_progress.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(RD.load_progress(os.path.join(self.root, "r")), {})


if __name__ == "__main__":
    unittest.main()
