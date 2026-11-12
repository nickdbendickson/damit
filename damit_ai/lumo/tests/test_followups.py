"""Tests for the PR #46 leftovers fixed in run_digest 1.2.0 / lumo_watch 1.2.0 (and DamIT Hazard 0.2.1's dam record):
one flag per id, receptors read the same at every hook, INFO flags in the flag list and the prompt, a measured first-byte
wait, and the toe distance from the run report. Synthetic fixtures and a local mock Ollama only; no model is run."""
import json
import os
import shutil
import sys
import tempfile
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
from strict import StrictCase, jload, slurp  # noqa: E402
from test_lumo_watch import MockOllama  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
try:
    from osgeo import gdal  # noqa: F401
    HAVE_GDAL = True
except ImportError:
    HAVE_GDAL = False
needs_numpy = unittest.skipUnless(HAVE_NUMPY, "numpy")


def flag(sev, fid, where="run", title="t"):
    return {"id": fid, "severity": sev, "where": where, "title": title, "detail": "", "data": {}}


class Base(StrictCase):
    def setUp(self):
        super(Base, self).setUp()
        self.root = tempfile.mkdtemp(prefix="lumo_follow_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = LW.settings()
        self.cfg.update(first_token_s=5.0, idle_s=1.0, wait_s=0.0, idle_gap_s=20.0)

    def mock(self, *a, **k):
        m = MockOllama(*a, **k)
        self.addCleanup(m.close)
        self.cfg["url"] = m.url
        return m

    def flags(self, d, fid):
        return [f for f in d["flags"] if f["id"] == fid]


# ---------------------------------------------------------------------------------------------- item 2: one flag per id
class TestOneFlagPerId(Base):
    def test_the_most_severe_is_kept_and_the_latest_among_equals(self):
        a, b, c = flag("WATCH", "X", "pass 1", "a"), flag("WATCH", "X", "pass 2", "b"), flag("PROBLEM", "X", "pass 3", "c")
        out = RD.dedupe_flags([a, b])
        self.assertEqual([(f["where"], f["title"]) for f in out], [("pass 2", "b")])          # equal: the latest
        out = RD.dedupe_flags([a, c, b])
        self.assertEqual([(f["where"], f["title"]) for f in out], [("pass 3", "c")])          # the most severe wins
        self.assertEqual(out[0]["data"]["occurrences"], 3)
        self.assertEqual([x["where"] for x in out[0]["data"]["also"]], ["pass 1", "pass 2"])
        self.assertIn("Also raised at pass 1, pass 2", out[0]["detail"])

    def test_other_ids_and_their_order_are_untouched_and_the_verdict_is_the_same(self):
        items = [flag("WATCH", "A", "pass 1"), flag("INFO", "B"), flag("WATCH", "A", "pass 2"), flag("PROBLEM", "C")]
        out = RD.dedupe_flags(items)
        self.assertEqual([f["id"] for f in out], ["A", "B", "C"])
        self.assertEqual(RD.verdict_of(out), RD.verdict_of(items))
        self.assertIsNone(items[0]["data"].get("occurrences"), "the input flags are not changed")
        self.assertEqual(RD.dedupe_flags([]), [])

    @needs_numpy
    def test_edge_outflow_early_is_listed_once_everywhere(self):
        run, dam = FX.make_run(self.root)                           # passes 1 and 2 leak, 3 is clean
        r = LW.run_event(run, "run_end", os.path.join(self.root, "w"), lumo=False, cfg=self.cfg, dam_folder=dam)
        d = r["digest"]
        ids = [f["id"] for f in d["flags"]]
        self.assertEqual(len(ids), len(set(ids)), ids)
        early = self.flags(d, "EDGE_OUTFLOW_EARLY")[0]
        self.assertEqual((early["where"], early["data"]["occurrences"]), ("pass 2", 2))
        self.assertEqual(early["data"]["also"][0]["where"], "pass 1")
        self.assertEqual(d["flags_text"].count("EDGE_OUTFLOW_EARLY"), 1)
        self.assertEqual(d["text"].split("FLAGS (")[1].splitlines()[0].count("EDGE_OUTFLOW_EARLY"), 1)
        lv = jload(os.path.join(r["out_dir"], "latest_verdict.json"))
        self.assertEqual(lv["flags"].count("EDGE_OUTFLOW_EARLY"), 1)
        self.assertEqual(len(lv["flags"]), len(set(lv["flags"])))
        self.assertEqual(r["verdict"], "WATCH")

    def test_latest_verdict_never_repeats_an_id_even_for_a_hand_built_digest(self):
        d = {"verdict": "WATCH", "phase": "run_end", "text": "x", "flags": [
            flag("WATCH", "EDGE_OUTFLOW_EARLY", "pass 1"), flag("WATCH", "EDGE_OUTFLOW_EARLY", "pass 2"),
            flag("INFO", "DAM_RECORD_MISSING"), flag("INFO", "DAM_RECORD_MISSING")]}
        LW.write_digest(self.root, d, "run_end")
        lv = jload(os.path.join(self.root, "latest_verdict.json"))
        self.assertEqual(lv["flags"], ["EDGE_OUTFLOW_EARLY"])
        self.assertEqual(lv["info_flags"], ["DAM_RECORD_MISSING"])


# ---------------------------------------------------------------------------------------------- item 3: receptors
@needs_numpy
class TestReceptorsReadTheSameAtEveryHook(Base):
    ROWS = None

    def rows(self):
        return FX.receptor_rows() + [("900000005", ) + FX.centre(*FX.DRY_ZERO_BESIDE_DEEP)]

    def ids_by_flag(self, d):
        return {fid: sorted((self.flags(d, fid) or [{"data": {"ids": []}}])[0]["data"]["ids"])
                for fid in ("RECEPTOR_NODATA", "RECEPTOR_DRY_NEXT_TO_WET")}

    def test_runner_nodata_turns_dry_and_missing_cells_into_nodata(self):
        import numpy as np
        g = RD.Grid(np.array([[0.0, -1.0, np.nan, 0.05, 2.0]]), 0, 50, 50)
        n = RD.runner_nodata(g)
        self.assertEqual(np.isnan(n.data).tolist(), [[True, True, True, False, False]])
        self.assertEqual((n.x0, n.y0, n.cell), (g.x0, g.y0, g.cell))
        self.assertEqual(g.data[0, 0], 0.0, "the input grid is not changed")

    def test_a_pass_hook_and_run_end_agree_on_every_receptor(self):
        run, dam = FX.make_run(self.root)
        pts = FX.write_points(self.root, self.rows())
        end = RD.build_digest(run, "run_end", dam_folder=dam, points_path=pts)
        want = {"RECEPTOR_NODATA": ["900000001", "900000005"],       # the DEM pocket, and a 0.0 dry cell beside the water
                "RECEPTOR_DRY_NEXT_TO_WET": ["900000003"]}           # only a trace of water counts as "dry"
        self.assertEqual(self.ids_by_flag(end), want)
        for n in (1, 2, 3):                                          # every pass hook (live: the pass's own grid)
            hook = RD.build_digest(run, "pass_end", dam_folder=dam, points_path=pts, upto_pass=n)
            self.assertEqual(self.ids_by_flag(hook), want, "pass hook %d" % n)

    def test_the_flag_says_which_grid_it_was_sampled_on(self):
        run, dam = FX.make_run(self.root)
        pts = FX.write_points(self.root, self.rows())
        live = RD.build_digest(run, "pass_end", dam_folder=dam, points_path=pts, upto_pass=2)
        f = self.flags(live, "RECEPTOR_NODATA")[0]
        self.assertIn("in progress", f["data"]["grid_source"])
        self.assertIn("Sampled on the run02_50m pass grid", f["detail"])

    @unittest.skipUnless(HAVE_GDAL, "GDAL")
    def test_the_runners_geotiff_gives_the_same_ids_as_the_pass_grid(self):
        import numpy as np
        from osgeo import gdal
        gdal.UseExceptions()
        run, dam = FX.make_run(self.root)
        pts = FX.write_points(self.root, self.rows())
        before = RD.build_digest(run, "run_end", dam_folder=dam, points_path=pts)
        os.makedirs(os.path.join(run, "outputs"))
        arr = np.full((FX.NROWS, FX.NCOLS), -9999.0, dtype="float32")     # the Runner writes depth <= 0 as NoData
        arr[5:13, 5:13] = 6.56
        arr[FX.DRY_BESIDE_DEEP] = 0.0656
        arr[FX.POCKET] = -9999
        ds = gdal.GetDriverByName("GTiff").Create(os.path.join(run, "outputs", "Depth (Max).tif"), FX.NCOLS, FX.NROWS, 1,
                                                  gdal.GDT_Float32)
        ds.SetGeoTransform((0, 50, 0, 1000, 0, -50))
        b = ds.GetRasterBand(1)
        b.SetNoDataValue(-9999)
        b.WriteArray(arr)
        b = ds = None
        after = RD.build_digest(run, "run_end", dam_folder=dam, points_path=pts)
        self.assertEqual(self.ids_by_flag(after), self.ids_by_flag(before))
        self.assertEqual(self.flags(after, "RECEPTOR_NODATA")[0]["data"]["grid_source"], "outputs/Depth (Max).tif")


# ---------------------------------------------------------------------------------------------- item 4: INFO flags
@needs_numpy
class TestInfoFlagsGetBullets(Base):
    def make(self, **kw):
        run, dam = FX.make_run(self.root, dam_record=False, **kw)
        return LW.run_event(run, "run_end", os.path.join(self.root, "w"), lumo=False, cfg=self.cfg, dam_folder=dam)

    def test_the_flag_list_and_the_prompt_cover_every_severity(self):
        r = self.make()
        d = r["digest"]
        info = [f["id"] for f in d["flags"] if f["severity"] == "INFO"]
        self.assertIn("DAM_RECORD_MISSING", info)
        self.assertIn("TOE_SOURCE_RUN_REPORT", info)
        self.assertEqual(sorted(f["id"] for f in d["flags"]), sorted(f["id"] for f in d["flags"] if f["id"] in d["flags_text"]))
        self.assertIn("%d INFO" % len(info), d["flags_text"])
        u = LW.build_user_prompt(d, "run_end")
        for i in info:
            self.assertIn("INFO | %s |" % i, u)
        self.assertIn("one bullet for each of the %d flag" % len(d["flags"]), u)
        self.assertEqual(len(LW.flag_lines(d)), len(d["flags"]))
        self.assertEqual(len(LW.flag_lines(d, include_info=False)), len(d["flags"]) - len(info))

    def test_the_system_prompt_asks_for_a_bullet_on_info_flags_too(self):
        s = LW.system_prompt()
        self.assertIn("EVERY flag in the FLAGS list, whatever its severity (PROBLEM, WATCH and INFO)", s)
        self.assertIn("An INFO flag is a note, not a concern", s)
        self.assertNotIn("EVERY WATCH or PROBLEM flag", s)
        self.assertEqual(slurp(os.path.join(LUMO, "prompts", "watcher_system.md")).strip(), s.strip())

    def test_an_info_flag_lumo_skips_is_named_in_the_footer_and_the_status(self):
        r = self.make()
        d = r["digest"]
        warn = sorted({f["id"] for f in d["flags"] if f["severity"] != "INFO"})
        m = self.mock([("piece", "\n".join("- %s: ok" % i for i in warn) + "\nVerdict: WATCH"), ("done",)])
        st = LW.explain(r["digest_path"], self.cfg)
        self.assertEqual(sorted(st["flags_missing"]), ["DAM_RECORD_MISSING", "TOE_SOURCE_RUN_REPORT"])
        sent = m.requests[-1]["messages"][1]["content"]                 # the prompt Lumo got names the INFO flags
        self.assertIn("INFO | DAM_RECORD_MISSING |", sent)
        md = slurp(os.path.join(r["out_dir"], "lumo_run_end.md"))
        self.assertIn("Not commented on by Lumo (done): DAM_RECORD_MISSING (INFO: ", md)
        self.assertIn("TOE_SOURCE_RUN_REPORT (INFO: toe from run_report, no dam_line)", md)

    def test_covering_the_info_flags_leaves_no_footer(self):
        r = self.make()
        every = sorted({f["id"] for f in r["digest"]["flags"]})
        self.mock([("piece", "\n".join("- %s: ok" % i for i in every) + "\nVerdict: WATCH"), ("done",)])
        st = LW.explain(r["digest_path"], self.cfg)
        self.assertEqual(st["flags_missing"], [])
        self.assertNotIn("Not commented", slurp(os.path.join(r["out_dir"], "lumo_run_end.md")))

    def test_latest_verdict_lists_info_ids_apart_from_the_verdict_ones(self):
        r = self.make()
        lv = jload(os.path.join(r["out_dir"], "latest_verdict.json"))
        self.assertIn("DAM_RECORD_MISSING", lv["info_flags"])
        self.assertNotIn("DAM_RECORD_MISSING", lv["flags"])


# ---------------------------------------------------------------------------------------------- item 5: first byte
class TestFirstByteWait(Base):
    def stream(self, script, **kw):
        self.mock(script)
        out = os.path.join(self.root, "o.md")
        return LW.stream_chat(LW.chat_payload([{"role": "user", "content": "hi"}], self.cfg), self.cfg["url"], out,
                              os.path.join(self.root, "s.json"), **kw)

    def test_the_measured_wait_is_recorded_not_the_cap(self):
        st = self.stream([("wait", 0.7), ("piece", "hello"), ("done",)], first_token_s=30.0, idle_s=5)
        self.assertEqual(st["status"], "done")
        self.assertGreaterEqual(st["first_byte_wait_s"], 0.6)
        self.assertLess(st["first_byte_wait_s"], 10.0)
        self.assertNotEqual(st["first_byte_wait_s"], 30.0)
        self.assertEqual(st["first_token_cap_s"], 30.0)
        self.assertLessEqual(st["first_byte_wait_s"], st["first_piece_s"] + 0.01)
        disk = jload(os.path.join(self.root, "s.json"))
        self.assertEqual((disk["first_byte_wait_s"], disk["first_token_cap_s"]), (st["first_byte_wait_s"], 30.0))

    def test_a_quick_server_is_a_small_number(self):
        st = self.stream([("piece", "a"), ("done",)], first_token_s=600.0, idle_s=5)
        self.assertLess(st["first_byte_wait_s"], 5.0)
        self.assertEqual(st["first_token_cap_s"], 600.0)

    def test_a_wait_that_runs_out_records_the_seconds_actually_waited(self):
        st = self.stream([("wait", 3.0), ("piece", "late"), ("done",)], first_token_s=0.5, idle_s=5)
        self.assertEqual(st["status"], "timeout")
        self.assertGreaterEqual(st["first_byte_wait_s"], 0.4)
        self.assertLess(st["first_byte_wait_s"], 2.5)
        self.assertEqual(st["first_token_cap_s"], 0.5)

    def test_nothing_is_recorded_when_the_server_is_not_there(self):
        out = os.path.join(self.root, "o.md")
        st = LW.stream_chat(LW.chat_payload([{"role": "user", "content": "hi"}], self.cfg), "http://127.0.0.1:1", out,
                            os.path.join(self.root, "s.json"), first_token_s=2.0, idle_s=1)
        self.assertEqual(st["status"], "unavailable")
        self.assertIsNone(st["first_byte_wait_s"])


# ---------------------------------------------------------------------------------------------- item 6: toe source
@needs_numpy
class TestToeSource(Base):
    def test_a_report_distance_with_no_dam_line_is_an_info_note_with_its_source(self):
        run, dam = FX.make_run(self.root)                            # toe 39 m in the report, no dam_line.geojson
        d = RD.build_digest(run, dam_folder=dam)
        self.assertEqual(self.flags(d, "TOE_UNCHECKED"), [])
        f = self.flags(d, "TOE_SOURCE_RUN_REPORT")
        self.assertEqual([(x["severity"], x["title"]) for x in f], [("INFO", "toe from run_report, no dam_line")])
        self.assertEqual(f[0]["data"]["distance_m"], 39.0)
        self.assertEqual(f[0]["data"]["distance_source"], "run_report, no dam_line")
        self.assertFalse(f[0]["data"]["dam_line_found"])
        self.assertIn("39 m", f[0]["detail"])
        self.assertIn("Toe inflow: 39 m from the dam line (toe from run_report, no dam_line)", d["text"])
        self.assertNotIn("TOE_UNCHECKED", d["flags_text"])
        self.assertEqual(d["checks"]["toe_inflow"]["distance_source"], "run_report, no dam_line")

    def test_it_never_changes_the_verdict(self):
        run, dam = FX.make_run(self.root, streambed_ft=1463.0, passes=2)        # a clean run
        d = RD.build_digest(run, dam_folder=dam)
        self.assertEqual([f["id"] for f in d["flags"] if f["id"].startswith("TOE")], ["TOE_SOURCE_RUN_REPORT"])
        self.assertEqual(d["verdict"], "OK")

    def test_with_a_dam_line_there_is_no_note_and_the_source_is_plain(self):
        run, dam = FX.make_run(self.root)
        with open(os.path.join(dam, "dam_line.geojson"), "w", encoding="utf-8") as f:
            json.dump({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, f)
        d = RD.build_digest(run, dam_folder=dam)
        self.assertEqual([f["id"] for f in d["flags"] if f["id"].startswith("TOE")], [])
        self.assertEqual(d["checks"]["toe_inflow"]["distance_source"], "run_report")
        self.assertNotIn("toe from run_report", d["text"])

    def test_no_distance_in_the_report_is_still_unchecked_and_has_no_source_note(self):
        run, dam = FX.make_run(self.root, inflow_how="lowest ground near the dam point")
        d = RD.build_digest(run, dam_folder=dam)
        self.assertEqual([f["id"] for f in d["flags"] if f["id"].startswith("TOE")], ["TOE_UNCHECKED"])

    def test_a_report_distance_outside_the_band_is_still_a_problem(self):
        run, dam = FX.make_run(self.root, toe_distance=80)
        d = RD.build_digest(run, dam_folder=dam)
        self.assertIn("TOE_INFLOW", [f["id"] for f in d["flags"] if f["severity"] == "PROBLEM"])
        self.assertTrue(self.flags(d, "TOE_SOURCE_RUN_REPORT"))
        self.assertEqual(d["verdict"], "PROBLEM")

    def test_the_documented_decision_is_in_the_knowledge_pack(self):
        t = slurp(os.path.join(LUMO, "knowledge", "WATCHER-DIGEST.md"))
        for needle in ("TOE_SOURCE_RUN_REPORT", "toe from run_report, no dam_line", "one flag per id", "INFO notes included",
                       "first_byte_wait_s", "first_token_cap_s", "Receptors read the same at every hook"):
            self.assertIn(needle.lower(), t.lower(), needle)


# ---------------------------------------------------------------------------------------------- item 1: Hazard handshake
@needs_numpy
class TestHazardFindsTheWatcherCopy(Base):
    def test_the_file_the_watcher_writes_is_the_file_damit_hazard_looks_for(self):
        """lumo_watch writes <watch>/<dam id>_<run folder>/dam_record_hazard.json; DamIT Hazard 0.2.1 finds it from a raster
        in that run folder with no DAM_JSON (damit_hazard/engine/dam_record.py, pure Python)."""
        from damit_hazard.engine import dam_record
        run, dam = FX.make_run(self.root, dam_record=False)
        old = os.environ.get("HOME")
        os.environ["HOME"] = self.root                                 # default_out_dir is ~/local-ai/watch/<dam>_<run>
        try:
            r = LW.run_event(run, "pass_end", None, pass_no=1, lumo=False, cfg=self.cfg, dam_folder=dam)
        finally:
            if old is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old
        self.assertTrue(r["hazard_dam_record"].endswith("TST00001_run_20260101_000000/dam_record_hazard.json"), r["hazard_dam_record"])
        tif = os.path.join(run, "outputs", "Depth (Max).tif")
        found, kind = dam_record.discover([tif], base=os.path.join(self.root, "local-ai", "watch"))
        self.assertEqual(found, r["hazard_dam_record"])
        self.assertIn("run watcher copy", kind)
        flat, nested = dam_record.load(found)
        self.assertFalse(nested)
        self.assertEqual((flat["dam_id"], flat["nid_id"]), ("TST00001", "TST00001"))


if __name__ == "__main__":
    unittest.main()
