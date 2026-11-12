"""Tests for the fixes to PR #46 (run digest 1.1.0 / lumo_watch 1.1.0, now 1.2.0): a missing dam record, the complete flag list,
Ollama timings and thinking, a busy Ollama, Lumo never competing with LISFLOOD, flushed logs and clean resources."""
import contextlib
import io
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LUMO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(LUMO, "tools"))
sys.path.insert(0, HERE)
import fixture_run as FX  # noqa: E402
import lumo_watch as LW  # noqa: E402
import run_digest as RD  # noqa: E402
from strict import StrictCase, jdump, jload, slurp  # noqa: E402
from test_lumo_watch import MockOllama  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False
needs_numpy = unittest.skipUnless(HAVE_NUMPY, "numpy")


class Base(StrictCase):
    def setUp(self):
        super(Base, self).setUp()
        self.root = tempfile.mkdtemp(prefix="lumo_fix46_")
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


# ------------------------------------------------------------------------------------------------ 2, 3, 10
@needs_numpy
class TestNoDamRecord(Base):
    def digest(self, **kw):
        run, dam = FX.make_run(self.root, dam_record=False, **kw)
        return RD.build_digest(run, dam_folder=dam, points_path=FX.write_points(self.root)), run, dam

    def test_no_false_datum_alarm_when_the_elevations_are_navd88_range(self):
        d, _, _ = self.digest(top_ft=1268.91, streambed_ft=1229.91)
        self.assertEqual(self.flags(d, "DATUM"), [])
        self.assertEqual(d["checks"]["datum"]["basis"], "NAVD88 range (no datum stated)")
        self.assertFalse(d["checks"]["dam"]["has_record"])

    def test_a_local_range_elevation_is_still_a_datum_problem_without_a_record(self):
        d, _, _ = self.digest(top_ft=120.0, streambed_ft=83.0)
        f = self.flags(d, "DATUM")
        self.assertEqual(len(f), 1)
        self.assertIn("LOCAL datum", f[0]["title"])
        self.assertEqual(f[0]["severity"], "WATCH")           # no DWR source to prove it, so WATCH not PROBLEM

    def test_an_unknown_datum_is_an_info_note_not_a_datum_problem(self):
        fl = RD.Flags()
        facts = {"top_ft": None, "stated_datum": None, "top_source": None, "has_record": False}
        RD.check_datum(facts, fl)
        self.assertEqual([(f["id"], f["severity"], f["title"]) for f in fl.items],
                         [("DATUM", "INFO", "unknown datum (no dam record)")])
        self.assertEqual(RD.verdict_of(fl.items), "OK")

    def test_a_stated_other_datum_is_still_a_problem(self):
        fl = RD.Flags()
        RD.check_datum({"top_ft": 1268.0, "stated_datum": "NGVD29", "top_source": "DWR", "has_record": True}, fl)
        self.assertEqual(fl.items[0]["severity"], "PROBLEM")

    def test_the_height_label_says_the_breach_bottom_stands_in_for_the_streambed(self):
        d, _, _ = self.digest()
        h = self.flags(d, "HEIGHT_MISMATCH")[0]
        self.assertIn("breach bottom used as streambed (no streambed in dam record)", h["title"])
        self.assertNotIn("(BOTTOM_FT)", h["title"])
        self.assertEqual(d["checks"]["height"]["bed_source"], "BOTTOM_FT")
        self.assertIn("breach bottom used as streambed", d["text"])
        self.assertIn("no streambed elevation", h["detail"])

    def test_with_a_record_the_label_is_plain_streambed(self):
        run, dam = FX.make_run(self.root)
        h = self.flags(RD.build_digest(run, dam_folder=dam), "HEIGHT_MISMATCH")[0]
        self.assertTrue(h["title"].startswith("crest minus streambed is 39.0 ft"))
        self.assertEqual(self.flags(RD.build_digest(run, dam_folder=dam), "DAM_RECORD_MISSING"), [])

    def test_the_missing_record_is_one_info_flag_and_never_changes_the_verdict(self):
        d, _, _ = self.digest()
        f = self.flags(d, "DAM_RECORD_MISSING")
        self.assertEqual([x["severity"] for x in f], ["INFO"])
        d2 = RD.build_digest(FX.make_run(os.path.join(self.root, "b"))[0])          # same run, with a record
        self.assertEqual(d["verdict"], d2["verdict"])

    def test_the_dam_id_comes_from_the_handoff_then_the_folder_name(self):
        d, run, dam = self.digest(setup_dam_id=False, handoff=True)
        self.assertEqual((d["dam_id"], d["checks"]["dam"]["dam_id_source"]), ("TST00001", "damit_handoff.json"))
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        d, _, _ = self.digest(setup_dam_id=False, handoff=False)
        self.assertEqual((d["dam_id"], d["checks"]["dam"]["dam_id_source"]), ("TST00001", "dam folder name"))

    def test_an_explicit_dam_folder_wins_even_without_a_dam_json(self):
        run, dam = FX.make_run(self.root)                          # the run's own setup points at a folder WITH a dam.json
        empty = os.path.join(self.root, "empty", "TST00001")
        os.makedirs(empty)
        d = RD.build_digest(run, dam_folder=empty)
        self.assertFalse(d["checks"]["dam"]["has_record"])
        self.assertEqual(len(self.flags(d, "DAM_RECORD_MISSING")), 1)
        self.assertTrue(RD.build_digest(run)["checks"]["dam"]["has_record"])

    def test_a_structure_layer_that_is_not_there_is_said_not_ignored(self):
        run, dam = FX.make_run(self.root)
        d = RD.build_digest(run, dam_folder=dam, structures_path=os.path.join(self.root, "nope.gpkg"))
        f = self.flags(d, "RECEPTORS_UNCHECKED")
        self.assertEqual(len(f), 1)
        self.assertIn("not found", f[0]["title"])

    def test_the_dam_id_prefers_the_run_record(self):
        d, _, _ = self.digest()
        self.assertEqual(d["checks"]["dam"]["dam_id_source"], "run_setup.dam")

    def test_the_toe_check_is_skipped_with_a_flag_when_the_report_gives_no_distance(self):
        how = "fallback (no toe-band cell): lowest ground within 90 m of the dam point, 44.8 ft below the top of dam"
        d, _, _ = self.digest(inflow_how=how)
        f = self.flags(d, "TOE_UNCHECKED")
        self.assertEqual([x["severity"] for x in f], ["WATCH"])
        self.assertIn("no distance from the dam line", f[0]["title"])
        self.assertIn("no dam_line.geojson was found", f[0]["detail"])
        self.assertIn(how, f[0]["detail"])
        self.assertEqual(self.flags(d, "TOE_INFLOW"), [])
        self.assertEqual(self.flags(d, "TOE_BAND"), [])                       # the band itself is still checked and fine

    def test_a_plain_missing_distance_is_info_only(self):
        d, _, _ = self.digest(inflow_how="lowest ground in the toe band")
        self.assertEqual([x["severity"] for x in self.flags(d, "TOE_UNCHECKED")], ["INFO"])

    def test_a_stated_distance_is_checked_as_before(self):
        d, _, _ = self.digest(toe_distance=120.0)
        self.assertEqual(self.flags(d, "TOE_UNCHECKED"), [])
        self.assertEqual(len(self.flags(d, "TOE_INFLOW")), 1)

    def test_a_flat_dam_record_for_hazard_is_written_beside_the_digest(self):
        d, run, dam = self.digest(setup_dam_id=False, handoff=True)
        rec = LW.flat_dam_record(d)
        self.assertEqual((rec["dam_id"], rec["nid_id"]), ("TST00001", "TST00001"))
        self.assertIn("dam_id", rec)                       # top level, not nested under "fields"
        out = os.path.join(self.root, "w")
        r = LW.run_event(run, "before_hazard", out, lumo=False, cfg=self.cfg, dam_folder=dam)
        self.assertEqual(r["hazard_dam_record"], os.path.join(out, "dam_record_hazard.json"))
        self.assertEqual(jload(r["hazard_dam_record"])["dam_id"], "TST00001")
        self.assertFalse(os.path.exists(os.path.join(dam, "dam_record_hazard.json")))       # never into the dam folder
        self.assertFalse(os.path.exists(os.path.join(run, "dam_record_hazard.json")))

    def test_no_dam_id_at_all_writes_no_record(self):
        self.assertIsNone(LW.flat_dam_record({"checks": {"dam": {"dam_id": None}}}))


# ------------------------------------------------------------------------------------------------ 1, A, D, E
@needs_numpy
class TestDigestText(Base):
    def test_domain_edge_wording_never_blames_the_breach(self):
        run, dam = FX.make_run(self.root, final_leak=True)
        d = RD.build_digest(run, dam_folder=dam)
        titles = " ".join(f["title"] + " " + f["detail"] for f in d["flags"] if f["id"].startswith("EDGE_"))
        self.assertIn("model domain edge", titles)
        self.assertNotRegex(titles.lower(), r"edge of the breach|breach edge")
        early = [f for f in d["flags"] if f["id"] == "EDGE_OUTFLOW_EARLY"][0]
        self.assertIn("not the breach", early["detail"])

    def test_receptor_ids_are_in_the_digest_text_the_flag_list_and_the_prompt(self):
        run, dam = FX.make_run(self.root)
        d = RD.build_digest(run, dam_folder=dam, points_path=FX.write_points(self.root))
        self.assertIn("ids 900000001", d["text"])
        self.assertIn("ids 900000001", d["flags_text"])
        self.assertIn("ids 900000001", LW.build_user_prompt(d, "run_end"))

    def test_ids_are_capped_at_ten_and_a_count(self):
        f = {"data": {"ids": [str(100 + i) for i in range(25)]}}
        t = RD.flag_ids_text(f)
        self.assertEqual(t, "ids " + ", ".join(str(100 + i) for i in range(10)) + " (+15 more)")
        self.assertEqual(RD.flag_ids_text({"data": {}}), "")
        self.assertEqual(RD.flag_ids_text({"data": {"ids": ["1", "2"]}}), "ids 1, 2")
        self.assertEqual(LW.flag_hint(f, 3), "ids 100, 101, 102 (+22 more)")

    def test_every_flag_is_listed_by_code_even_when_the_summary_is_cut(self):
        run, dam = FX.make_run(self.root)
        d = RD.build_digest(run, dam_folder=dam)
        for i in range(50):
            d["flags"].append({"id": "ROADS_UNSCORED", "severity": "WATCH", "where": "hazard #%d" % i,
                               "title": "t%d" % i, "detail": "", "data": {}})
        text, full = RD.render_text(d), RD.render_flag_list(d)
        self.assertLessEqual(len(text.splitlines()), 40)
        self.assertIn("more flag(s): see the complete flag list", text)
        self.assertEqual(len([l for l in full.splitlines() if l[:1].isdigit()]), len(d["flags"]))
        self.assertIn("t49", full)
        self.assertTrue(full.startswith("COMPLETE FLAG LIST - %d flag(s)" % len(d["flags"])))
        out = LW.write_digest(os.path.join(self.root, "w"), dict(d, flags_text=full, text=text), "run_end")
        self.assertIn("t49", slurp(out[:-5] + ".txt"))              # the saved text file carries the whole list too

    def test_info_notes_are_listed_last_in_the_complete_list(self):
        run, dam = FX.make_run(self.root, dam_record=False)
        d = RD.build_digest(run, dam_folder=dam)
        lines = [l for l in d["flags_text"].splitlines() if l[:1].isdigit()]
        sev = [l.split("]")[0].split("[")[1] for l in lines]
        self.assertIn("[INFO] DAM_RECORD_MISSING", " ".join(lines))
        first_info = sev.index("INFO")
        self.assertTrue(all(s == "INFO" for s in sev[first_info:]), sev)       # every INFO note comes after every other flag

    def test_missing_gdal_is_an_info_flag_not_a_silent_gap(self):
        run, dam = FX.make_run(self.root)
        rp = os.path.join(run, "run_report.json")
        r = jload(rp)
        r["crs_wkt"] = "PROJCS[\"x\"]"
        jdump(r, rp)
        shp = os.path.join(self.root, "structures.gpkg")
        with open(shp, "wb") as f:
            f.write(b"x")
        old = RD.load_points_ogr
        RD.load_points_ogr = lambda *a, **k: None                  # what it returns when osgeo cannot be imported
        self.addCleanup(setattr, RD, "load_points_ogr", old)
        d = RD.build_digest(run, dam_folder=dam, structures_path=shp)
        f = self.flags(d, "RECEPTORS_UNCHECKED")
        self.assertEqual([x["severity"] for x in f], ["INFO"])
        self.assertIn("GDAL/OGR is not installed", f[0]["title"])
        self.assertEqual(self.flags(d, "RECEPTOR_NODATA"), [])
        self.assertIsNotNone(d["checks"]["peaks"])                  # the rest of the digest is unaffected

    def _raising(self, exc):
        old = RD._pass_grid
        self.addCleanup(setattr, RD, "_pass_grid", old)

        def boom(*a, **k):
            raise exc
        RD._pass_grid = boom

    def test_a_raster_error_with_an_empty_message_names_its_type_and_a_traceback(self):
        run, dam = FX.make_run(self.root)
        self._raising(RuntimeError())
        f = self.flags(RD.build_digest(run, dam_folder=dam), "NO_RUN_FILES")[0]
        self.assertIn("RuntimeError (no message)", f["title"])
        self.assertIn("traceback tail", f["detail"])
        self.assertIn("boom", f["detail"])
        self.assertEqual(f["data"]["error_type"], "RuntimeError")

    def test_a_proj_database_error_says_how_to_fix_it(self):
        run, dam = FX.make_run(self.root)
        self._raising(RuntimeError("proj_create: Cannot find proj.db"))
        f = self.flags(RD.build_digest(run, dam_folder=dam), "NO_RUN_FILES")[0]
        self.assertIn("proj.db", f["title"])
        self.assertIn("PROJ_DATA", f["detail"])
        self.assertIn("PROJ_LIB", f["detail"])

    def test_versions(self):
        self.assertEqual(RD.VERSION, "1.2.0")
        self.assertEqual(LW.VERSION, "1.2.0")

    def test_docs_describe_proj_and_the_no_record_case(self):
        t = slurp(os.path.join(LUMO, "knowledge", "WATCHER-DIGEST.md"))
        for needle in ("PROJ_DATA", "PROJ_LIB", "proj.db", "dam_record_hazard.json", "No dam.json in the dam folder",
                       "TOE_UNCHECKED", "unknown datum (no dam record)", "breach bottom used as streambed",
                       "model domain edge", "not dam leakage", "LUMO_WATCH_EXPLAIN", "LUMO_WATCH_NUM_THREAD",
                       "LUMO_WATCH_FIRST_TOKEN_S", "prompt_eval_duration", "thinking_despite_think_false"):
            self.assertIn(needle, t, needle)


class TestPromptWording(Base):
    def test_the_system_prompt_pins_domain_edge_and_no_invented_flag_ids(self):
        s = LW.system_prompt()
        self.assertIn("MODEL DOMAIN", s)
        self.assertIn("EXPECTED while the domain grows", s)
        self.assertIn("not dam leakage", s)
        self.assertIn("only flag ids are the ones in the FLAGS list", s)
        self.assertIn("ONE short bullet", s)
        self.assertNotRegex(s, r"(?i)at most 6")

    def test_no_pack_text_calls_domain_edge_outflow_the_edge_of_the_breach(self):
        for name in ("KNOWN-BEHAVIOURS.md", "WATCHER-DIGEST.md"):
            self.assertNotRegex(slurp(os.path.join(LUMO, "knowledge", name)).lower(), r"edge of the breach")

    @needs_numpy
    def test_every_flag_stays_in_the_prompt_even_over_budget(self):
        run, dam = FX.make_run(self.root, hazard=True, unscored_roads=11, mass_nan=True, final_leak=True)
        d = RD.build_digest(run, dam_folder=dam, points_path=FX.write_points(self.root))
        ids = {f["id"] for f in d["flags"]}                       # INFO ids too (1.2.0)
        for budget in (1000, 400, 120):
            u = LW.build_user_prompt(d, "run_end", max_tokens=budget)
            for fid in ids:
                self.assertIn(fid, u, (budget, fid))
            self.assertIn("one bullet for each of the %d flag" % len(d["flags"]), u)

    def test_invented_ids_are_found_but_real_names_are_not(self):
        t = "- WITHIN_BREACH is bad. HEIGHT_MISMATCH 39 vs 37. Use --GRID_REFINE=0 and TOP_FT. NO_RUN_FILES"
        self.assertEqual(LW.invented_ids(t), ["WITHIN_BREACH"])


# ------------------------------------------------------------------------------------------------ 6
@needs_numpy
class TestCompleteFlagList(Base):
    def make(self, **kw):
        run, dam = FX.make_run(self.root, **kw)
        r = LW.run_event(run, "run_end", os.path.join(self.root, "w"), lumo=False, cfg=self.cfg, dam_folder=dam,
                         points_path=FX.write_points(self.root))
        return r

    def test_the_md_starts_with_every_flag_then_lumos_comments(self):
        r = self.make(hazard=True, unscored_roads=11, final_leak=True)
        self.mock([("piece", "- HEIGHT_MISMATCH: 39 vs 37 ft.\\n".replace("\\\\n", "\n")), ("piece", "Verdict: PROBLEM"), ("done",)])
        st = LW.explain(r["digest_path"], self.cfg)
        md = slurp(os.path.join(r["out_dir"], "lumo_run_end.md"))
        d = r["digest"]
        head, _, tail = md.partition("## Lumo's comments")
        self.assertIn("COMPLETE FLAG LIST", head)
        for f in d["flags"]:
            self.assertIn(f["id"], head)
        self.assertIn("HEIGHT_MISMATCH: 39 vs 37 ft", tail)
        self.assertLess(md.index("COMPLETE FLAG LIST"), md.index("HEIGHT_MISMATCH: 39"))
        self.assertEqual(st["flags_covered"], ["HEIGHT_MISMATCH"])
        self.assertIn("RECEPTOR_NODATA", st["flags_missing"])
        self.assertIn("Not commented on by Lumo (done):", md)
        self.assertEqual(jload(os.path.join(r["out_dir"], "lumo_run_end.status.json"))["flags_missing"], st["flags_missing"])

    def test_when_lumo_covers_everything_there_is_no_footer(self):
        r = self.make()
        ids = sorted({f["id"] for f in r["digest"]["flags"]})            # INFO ids too (1.2.0)
        self.mock([("piece", "\n".join("- %s: ok" % i for i in ids) + "\nVerdict: WATCH"), ("done",)])
        st = LW.explain(r["digest_path"], self.cfg)
        self.assertEqual(st["flags_missing"], [])
        self.assertNotIn("Not commented", slurp(os.path.join(r["out_dir"], "lumo_run_end.md")))

    def test_a_timeout_leaves_the_complete_list_on_disk(self):
        r = self.make()
        self.cfg.update(url="http://127.0.0.1:1", first_token_s=1.0)
        st = LW.explain(r["digest_path"], self.cfg)
        self.assertEqual(st["status"], "unavailable")
        md = slurp(os.path.join(r["out_dir"], "lumo_run_end.md"))
        self.assertIn("COMPLETE FLAG LIST", md)
        self.assertIn("Not commented on by Lumo (unavailable)", md)

    def test_invented_flag_ids_are_called_out_in_the_footer_and_the_status(self):
        r = self.make()
        ids = sorted({f["id"] for f in r["digest"]["flags"]})
        self.mock([("piece", "\n".join("- %s ok" % i for i in ids) + "\n- WITHIN_BREACH weak dam\nVerdict: WATCH"), ("done",)])
        st = LW.explain(r["digest_path"], self.cfg)
        self.assertEqual(st["invented_ids"], ["WITHIN_BREACH"])
        self.assertIn("not flags of this run: WITHIN_BREACH", slurp(os.path.join(r["out_dir"], "lumo_run_end.md")))

    def test_the_verdict_is_untouched_by_all_of_it(self):
        r = self.make()
        self.mock([("piece", "everything is fine, Verdict: OK"), ("done",)])
        LW.explain(r["digest_path"], self.cfg)
        self.assertEqual(jload(r["digest_path"])["verdict"], r["verdict"])


# ------------------------------------------------------------------------------------------------ 7, B, C
class TestOllamaFields(Base):
    def stream(self, script, mock_kw=None, **kw):
        m = self.mock(script, **(mock_kw or {}))
        out = os.path.join(self.root, "o.md")
        st = LW.stream_chat(LW.chat_payload([{"role": "user", "content": "hi"}], self.cfg), self.cfg["url"], out,
                            os.path.join(self.root, "s.json"), **kw)
        return m, out, st

    def test_every_ollama_timing_field_is_in_the_status_json(self):
        _, out, st = self.stream([("piece", "a"), ("done",)], first_token_s=5, idle_s=2)
        disk = jload(os.path.join(self.root, "s.json"))
        for k in ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count",
                  "eval_duration", "done_reason"):
            self.assertIn(k, disk, k)
        self.assertEqual(disk["prompt_eval_duration"], 14000000000)
        self.assertEqual(disk["prompt_eval_s"], 14.0)
        self.assertEqual(disk["load_s"], 1.5)
        self.assertEqual(disk["eval_tok_per_s"], 10.0)
        self.assertEqual(disk["prompt_tok_per_s"], 50.0)
        self.assertIsNotNone(disk["first_piece_s"])

    def test_timing_summary_ignores_missing_fields(self):
        self.assertEqual(LW.timing_summary({}), {})
        self.assertEqual(LW.timing_summary({"eval_count": 5}), {})

    def test_thinking_tokens_are_kept_and_flagged_when_they_arrive_despite_think_false(self):
        _, out, st = self.stream([("thinking", "hmm "), ("thinking", "wait"), ("piece", "answer"), ("done",)],
                                 first_token_s=5, idle_s=2)
        self.assertEqual(slurp(out), "answer")                       # never mixed into the answer
        self.assertEqual(slurp(out + ".thinking.txt"), "hmm wait")
        disk = jload(os.path.join(self.root, "s.json"))
        self.assertTrue(disk["thinking_despite_think_false"])
        self.assertEqual(disk["thinking_chars"], 8)
        self.assertIn("thinking tokens arrived although think:false", disk["error"])
        self.assertEqual(disk["status"], "done")

    def test_no_thinking_file_and_no_flag_when_none_arrives(self):
        _, out, st = self.stream([("piece", "a"), ("done",)], first_token_s=5, idle_s=2)
        self.assertFalse(os.path.exists(out + ".thinking.txt"))
        self.assertFalse(st["thinking_despite_think_false"])
        self.assertEqual(st["thinking_chars"], 0)
        self.assertIsNone(st["error"])

    def test_a_server_busy_before_the_first_byte_is_a_timeout_not_a_partial_answer(self):
        _, out, st = self.stream([("wait", 2.0), ("piece", "late"), ("done",)], first_token_s=0.4, idle_s=2)
        self.assertEqual(st["status"], "timeout")
        self.assertIn("busy with another job", st["error"])
        self.assertIn("LUMO_WATCH_FIRST_TOKEN_S", st["error"])
        self.assertEqual(st["chars"], 0)

    def test_a_server_that_sends_no_headers_yet_is_also_a_timeout(self):
        _, out, st = self.stream([("piece", "late"), ("done",)], {"header_delay": 1.5}, first_token_s=0.4, idle_s=2)
        self.assertEqual(st["status"], "timeout")
        self.assertNotEqual(st["status"], "unavailable")

    def test_timeout_after_some_text_is_partial(self):
        _, out, st = self.stream([("piece", "some"), ("wait", 3.0), ("done",)], first_token_s=2, idle_s=0.4)
        self.assertEqual(st["status"], "partial")
        self.assertEqual(slurp(out), "some")

    def test_the_first_byte_wait_is_configurable_and_zero_waits_without_limit(self):
        self.assertEqual(LW.settings()["first_token_s"], 600.0)
        os.environ["LUMO_WATCH_FIRST_TOKEN_S"] = "42"
        self.addCleanup(os.environ.pop, "LUMO_WATCH_FIRST_TOKEN_S", None)
        self.assertEqual(LW.settings()["first_token_s"], 42.0)
        _, out, st = self.stream([("wait", 1.0), ("piece", "late but whole"), ("done",)], first_token_s=0, idle_s=0)
        self.assertEqual(st["status"], "done")
        self.assertEqual(slurp(out), "late but whole")

    def test_wait_for_lumo_treats_timeout_as_finished(self):
        sp = os.path.join(self.root, "s.json")
        jdump({"status": "timeout"}, sp)
        self.assertEqual(LW.wait_for_lumo(sp, 2)["status"], "timeout")


# ------------------------------------------------------------------------------------------------ 8
class TestNeverSlowsLisflood(Base):
    def run_dir(self, **kw):
        run, dam = FX.make_run(self.root, **kw)
        return run

    def test_defaults(self):
        c = LW.settings()
        self.assertEqual((c["explain"], c["num_thread"], c["idle_gap_s"], c["nice"]), ("idle", 2, 20.0, 10))

    def test_configurable_by_environment(self):
        env = {"LUMO_WATCH_EXPLAIN": "end", "LUMO_WATCH_NUM_THREAD": "3", "LUMO_WATCH_IDLE_GAP_S": "5",
               "LUMO_WATCH_NICE": "0", "LUMO_WATCH_QUEUE_WAIT_S": "9"}
        for k, v in env.items():
            os.environ[k] = v
            self.addCleanup(os.environ.pop, k, None)
        c = LW.settings()
        self.assertEqual((c["explain"], c["num_thread"], c["idle_gap_s"], c["nice"], c["queue_wait_s"]), ("end", 3, 5.0, 0, 9.0))
        os.environ["LUMO_WATCH_EXPLAIN"] = "nonsense"
        self.assertEqual(LW.settings()["explain"], "idle")

    def test_num_thread_is_capped_in_the_request_and_zero_means_ollamas_default(self):
        msgs = [{"role": "user", "content": "x"}]
        self.assertEqual(LW.chat_payload(msgs, dict(self.cfg, num_thread=2))["options"]["num_thread"], 2)
        self.assertEqual(LW.chat_payload(msgs, dict(self.cfg, num_thread=5))["options"]["num_thread"], 5)
        self.assertNotIn("num_thread", LW.chat_payload(msgs, dict(self.cfg, num_thread=0))["options"])

    def test_the_cap_reaches_ollama_on_the_wire(self):
        m = self.mock([("piece", "a"), ("done",)])
        LW.stream_chat(LW.chat_payload([{"role": "user", "content": "x"}], dict(self.cfg, num_thread=2)), self.cfg["url"],
                       os.path.join(self.root, "o.md"), idle_s=2)
        self.assertEqual(m.requests[0]["options"]["num_thread"], 2)

    @needs_numpy
    def test_a_running_pass_is_busy(self):
        run = self.run_dir(unfinished=True, report=False)
        os.remove(os.path.join(run, "run_report.json")) if os.path.exists(os.path.join(run, "run_report.json")) else None
        s = jload(os.path.join(run, "run_setup.json"))
        s["status"] = "running"
        jdump(s, os.path.join(run, "run_setup.json"))
        st = LW.engine_state(run, self.cfg, proc=False)
        self.assertFalse(st["idle"])
        self.assertIn("still running", st["reason"])
        self.assertEqual(LW.explain_gate(run, dict(self.cfg, explain="idle"), proc=False)[0], False)

    @needs_numpy
    def test_a_finished_run_is_idle_unless_a_lisflood_process_runs(self):
        run = self.run_dir()
        self.assertTrue(LW.engine_state(run, self.cfg, proc=False)["idle"])
        st = LW.engine_state(run, self.cfg, proc=True)
        self.assertFalse(st["idle"])
        self.assertIn("lisflood process", st["reason"])

    @needs_numpy
    def test_between_passes_it_waits_for_a_quiet_gap(self):
        run = self.run_dir(report=False)
        s = jload(os.path.join(run, "run_setup.json"))
        s["status"] = "running"
        jdump(s, os.path.join(run, "run_setup.json"))
        now = time.time()
        for d in RD._pass_dirs(run):
            os.utime(os.path.join(d, "lisflood.log"), (now - 3, now - 3))
        st = LW.engine_state(run, dict(self.cfg, idle_gap_s=20.0), now=now, proc=False)
        self.assertFalse(st["idle"])
        self.assertIn("between passes", st["reason"])
        self.assertTrue(LW.engine_state(run, dict(self.cfg, idle_gap_s=2.0), now=now, proc=False)["idle"])
        self.assertTrue(LW.engine_state(run, dict(self.cfg, idle_gap_s=20.0), now=now + 60, proc=False)["idle"])

    @needs_numpy
    def test_modes(self):
        run = self.run_dir()
        for mode, want in (("never", False), ("always", True), ("idle", True), ("end", True)):
            self.assertEqual(LW.explain_gate(run, dict(self.cfg, explain=mode), proc=False)[0], want, mode)
        self.assertTrue(LW.explain_gate(run, dict(self.cfg, explain="always"), proc=True)[0])     # always = old behaviour
        self.assertFalse(LW.explain_gate(run, dict(self.cfg, explain="idle"), proc=True)[0])

    @needs_numpy
    def test_end_mode_waits_for_the_run_to_finish(self):
        run = self.run_dir(report=False)
        s = jload(os.path.join(run, "run_setup.json"))
        s["status"] = "running"
        jdump(s, os.path.join(run, "run_setup.json"))
        now = time.time() + 600                               # long past any gap: idle, but not finished
        ok, why = LW.explain_gate(run, dict(self.cfg, explain="end"), now=now, proc=False)
        self.assertFalse(ok)
        self.assertIn("finish", why)
        self.assertTrue(LW.explain_gate(run, dict(self.cfg, explain="idle"), now=now, proc=False)[0])

    @needs_numpy
    def test_a_busy_engine_queues_the_explanation_and_still_writes_the_digest(self):
        run = self.run_dir()
        spawned = []
        out = os.path.join(self.root, "w")
        r = LW.run_event(run, "run_end", out, lumo=True, cfg=self.cfg, spawn=lambda jp, c: spawned.append(jp),
                         probe=lambda rd, c: (False, "a lisflood process is running"))
        self.assertEqual(spawned, [])
        self.assertEqual(r["lumo"]["status"], "queued")
        self.assertIn("lisflood process", r["lumo"]["error"])
        self.assertIn("lumo_watch.py explain", r["lumo"]["later"])
        self.assertTrue(os.path.exists(os.path.join(out, "digest_run_end.json")))
        self.assertEqual(r["verdict"], "WATCH")

    @needs_numpy
    def test_an_idle_engine_starts_the_explanation(self):
        run = self.run_dir()
        spawned = []
        LW.run_event(run, "run_end", os.path.join(self.root, "w"), lumo=True, cfg=self.cfg,
                     spawn=lambda jp, c: spawned.append(jp), probe=lambda rd, c: (True, "idle"))
        self.assertEqual(len(spawned), 1)

    @needs_numpy
    def test_watch_queues_the_newest_event_until_lisflood_is_idle(self):
        run = self.run_dir()
        spawned, calls = [], []

        def probe(rd, c):
            calls.append(1)
            return (len(calls) >= 4, "busy" if len(calls) < 4 else "idle")
        res = LW.watch(run, os.path.join(self.root, "w"), poll_s=0.01, until="before_hazard", lumo=True,
                       cfg=dict(self.cfg, queue_wait_s=5.0), log=lambda *a: None, spawn=lambda jp, c: spawned.append(jp),
                       probe=probe)
        self.assertGreaterEqual(len(calls), 4)                          # it kept waiting for an idle engine
        self.assertEqual(len(spawned), 1)                               # one inference: the newest event only
        self.assertTrue(spawned[0].endswith("digest_before_hazard.json"))
        statuses = [r["lumo"]["status"] for r in res]
        self.assertEqual(statuses.count("skipped"), len(res) - 1)       # older events were replaced in the queue
        self.assertTrue(all(r["verdict"] for r in res))

    @needs_numpy
    def test_watch_leaves_it_queued_when_the_engine_never_goes_idle(self):
        run = self.run_dir()
        logs, spawned = [], []
        res = LW.watch(run, os.path.join(self.root, "w"), poll_s=0.01, until="before_hazard", lumo=True,
                       cfg=dict(self.cfg, queue_wait_s=0.2), log=logs.append, spawn=lambda jp, c: spawned.append(jp),
                       probe=lambda rd, c: (False, "busy"))
        self.assertEqual(spawned, [])
        self.assertEqual(res[-1]["lumo"]["status"], "queued")
        self.assertTrue(any("still queued" in l and "explain" in l for l in logs))

    @needs_numpy
    def test_watch_never_asks_lumo_in_never_mode(self):
        run = self.run_dir()
        res = LW.watch(run, os.path.join(self.root, "w"), until="before_hazard", lumo=True, cfg=dict(self.cfg, explain="never"),
                       once=True, log=lambda *a: None, spawn=lambda *a: self.fail("spawned"))
        self.assertTrue(all(r["lumo"] is None for r in res))

    def test_the_explain_process_gets_the_thread_cap_and_a_nice_level(self):
        seen = {}

        class FakeProc(object):
            pass

        def fake_popen(cmd, **kw):
            seen.update(cmd=cmd, kw=kw)
            return FakeProc()
        real = LW.subprocess.Popen
        LW.subprocess.Popen = fake_popen
        self.addCleanup(setattr, LW.subprocess, "Popen", real)
        jp = os.path.join(self.root, "digest_run_end.json")
        jdump({}, jp)
        LW.spawn_explain(jp, dict(self.cfg, num_thread=3, nice=7))
        self.assertEqual(seen["kw"]["env"]["LUMO_WATCH_NUM_THREAD"], "3")
        self.assertEqual(seen["kw"]["env"]["LUMO_WATCH_NUM_PREDICT"], str(self.cfg["num_predict"]))
        if os.name != "nt":
            self.assertTrue(callable(seen["kw"]["preexec_fn"]))
            self.assertTrue(seen["kw"]["start_new_session"])
        self.assertTrue(os.path.exists(jp[:-5] + ".lumo.log"))          # the log was opened and closed by the parent

    def test_lisflood_process_scan_can_be_switched_off(self):
        os.environ["LUMO_WATCH_PROC_SCAN"] = "0"
        self.addCleanup(os.environ.pop, "LUMO_WATCH_PROC_SCAN", None)
        self.assertIsNone(LW._lisflood_process_running())

    def test_the_cli_flags_set_the_mode_and_the_threads(self):
        run, dam = FX.make_run(self.root) if HAVE_NUMPY else (None, None)
        if run is None:
            self.skipTest("numpy")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            LW.main(["event", "run_end", run, "--dam-folder", dam, "--explain", "never", "--out", os.path.join(self.root, "o")])
        self.assertIn("Lumo: not asked", buf.getvalue())


# ------------------------------------------------------------------------------------------------ 4, 5
@needs_numpy
class TestFlushedLog(Base):
    def test_log_lines_reach_a_pipe_while_the_watcher_is_still_running(self):
        run, dam = FX.make_run(self.root)
        cmd = [sys.executable, os.path.join(LUMO, "tools", "lumo_watch.py"), "watch", run, "--dam-folder", dam, "--poll", "1",
               "--until", "after_hazard", "--no-lumo", "--out", os.path.join(self.root, "w")]
        env = dict(os.environ, PYTHONUNBUFFERED="")
        env.pop("PYTHONUNBUFFERED")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        try:
            self.assertTrue(select.select([p.stdout], [], [], 15)[0] if os.name != "nt" else True, "no output while running")
            line = p.stdout.readline().decode()
            self.assertIn("pass_end", line)
            self.assertIsNone(p.poll())                         # still polling: the line came before the process exited
        finally:
            p.terminate()
            p.wait(10)
            p.stdout.close()

    def test_the_default_log_flushes(self):
        flushed = []

        class Out(io.StringIO):
            def flush(self):
                flushed.append(1)
        buf = Out()
        with contextlib.redirect_stdout(buf):
            LW._log_line("x")
        self.assertEqual(flushed, [1])


class TestResources(unittest.TestCase):
    def test_the_strict_case_fails_on_an_unclosed_file(self):
        class Leaky(StrictCase):
            def test_leak(self):
                f = open(__file__, encoding="utf-8")
                f.read(1)
                del f

        res = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(Leaky))
        self.assertEqual(len(res.failures) + len(res.errors), 1)
        self.assertIn("ResourceWarning", (res.failures + res.errors)[0][1])

    def test_the_strict_case_fails_on_a_warning_raised_from_lumo_code(self):
        import warnings

        class Warny(StrictCase):
            def test_warn(self):
                warnings.warn_explicit("old api", DeprecationWarning, os.path.join(LUMO, "tools", "x.py"), 1)

        res = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(Warny))
        self.assertEqual(len(res.failures) + len(res.errors), 1)

    def test_the_tool_modules_never_open_a_file_without_closing_it(self):
        import re
        allowed = ("out = open(out_path", "think_out[0] = open(")      # both are closed in stream_chat's fin()
        for name in ("lumo_watch.py", "run_digest.py", "dump_damit_algorithm_help.py"):
            for i, line in enumerate(slurp(os.path.join(LUMO, "tools", name)).splitlines(), 1):
                code = line.split("#")[0]
                if re.search(r"(?<![\w.])open\(", code) and "with open(" not in code and not any(a in code for a in allowed):
                    self.fail("bare open() in %s:%d: %s" % (name, i, line.strip()))

    def test_stream_chat_closes_its_socket_and_file_on_every_path(self):
        m = MockOllama([("piece", "a"), ("done",)])
        self.addCleanup(m.close)
        out = tempfile.mkdtemp(prefix="lumo_res_")
        self.addCleanup(shutil.rmtree, out, True)
        cfg = LW.settings()
        for script in ([("piece", "a"), ("done",)], [("piece", "a"), ("drop",)]):
            m.script = script
            LW.stream_chat(LW.chat_payload([{"role": "user", "content": "x"}], cfg), m.url, os.path.join(out, "o.md"),
                           idle_s=1.0)
        LW.stream_chat(LW.chat_payload([{"role": "user", "content": "x"}], cfg), "http://127.0.0.1:1", os.path.join(out, "o.md"))


if __name__ == "__main__":
    unittest.main()
