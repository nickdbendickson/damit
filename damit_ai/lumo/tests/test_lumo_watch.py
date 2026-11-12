"""Tests for lumo_watch.py: the Ollama client (against a MOCK server: stream parsing, partial save, the think:false
payload), the prompt, the event hooks and the rule that the code's verdict never waits on, or changes with, Lumo.
No real Ollama and no model is ever called."""
import http.server
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LUMO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(LUMO, "tools"))
sys.path.insert(0, HERE)
import fixture_run as FX  # noqa: E402
from strict import StrictCase, jdump, jload, slurp, spit  # noqa: E402,F401
import lumo_watch as LW  # noqa: E402
import run_digest as RD  # noqa: E402


class MockOllama(object):
    """A tiny /api/chat server. script: a list of ('piece', text) | ('wait', seconds) | ('wait_event', Event) |
    ('drop',) | ('done',). Records every request body."""

    def __init__(self, script=None, status=200, body=None, header_delay=0.0):
        self.script = script if script is not None else [("piece", "ok"), ("done",)]
        self.requests = []
        self.paths = []
        outer = self
        self.fail_think_400 = False

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n))
                outer.requests.append(req)
                outer.paths.append(self.path)
                if header_delay:
                    time.sleep(header_delay)             # queued behind another job: no byte at all yet
                if outer.fail_think_400 and "think" in req:
                    data = json.dumps({"error": "\"phi4-mini\" does not support thinking"}).encode()
                    self.send_response(400)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if status != 200:
                    data = (body or "boom").encode()
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                def chunk(obj):
                    b = (json.dumps(obj) + "\n").encode()
                    self.wfile.write(("%x\r\n" % len(b)).encode() + b + b"\r\n")
                    self.wfile.flush()
                try:
                    for step in outer.script:
                        k = step[0]
                        if k == "piece":
                            chunk({"model": req.get("model"), "message": {"role": "assistant", "content": step[1]}, "done": False})
                        elif k == "thinking":
                            chunk({"model": req.get("model"), "message": {"role": "assistant", "content": "", "thinking": step[1]},
                                   "done": False})
                        elif k == "wait":
                            time.sleep(step[1])
                        elif k == "wait_event":
                            step[1].wait(10)
                        elif k == "drop":
                            self.connection.shutdown(socket.SHUT_RDWR)
                            return
                        elif k == "raw":
                            b = step[1].encode()
                            self.wfile.write(("%x\r\n" % len(b)).encode() + b + b"\r\n")
                            self.wfile.flush()
                        elif k == "done":
                            chunk({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                                   "prompt_eval_count": 700, "eval_count": 120,
                                   "total_duration": 30000000000, "load_duration": 1500000000,
                                   "prompt_eval_duration": 14000000000, "eval_duration": 12000000000})
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        class Quiet(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):      # a client that gave up is not a test failure
                pass

        self.srv = Quiet(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def free_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return "http://127.0.0.1:%d" % port


class Base(StrictCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lumo_watch_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = LW.settings()
        self.cfg.update(first_token_s=5.0, idle_s=1.0, wait_s=0.0)

    def mock(self, *a, **k):
        m = MockOllama(*a, **k)
        self.addCleanup(m.close)
        self.cfg["url"] = m.url
        return m

    def messages(self):
        run, dam = FX.make_run(self.root)
        d = RD.build_digest(run, dam_folder=dam)
        return d, LW.build_messages(d, "run_end")


class TestSettings(StrictCase):
    def setUp(self):
        self.env = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("LUMO_WATCH_")}
        self.addCleanup(os.environ.update, self.env)

    def test_default_explainer_is_the_4b_model(self):
        self.assertEqual(LW.settings()["model"], "qwen3:4b")

    def test_phi_is_the_option_and_any_tag_works(self):
        self.assertEqual(LW.resolve_model("phi"), "phi4-mini")
        self.assertEqual(LW.resolve_model("small"), "qwen3:4b")
        self.assertEqual(LW.resolve_model("qwen3:8b"), "qwen3:8b")

    def test_model_is_configurable_by_env(self):
        os.environ["LUMO_WATCH_MODEL"] = "phi"
        self.assertEqual(LW.settings()["model"], "phi4-mini")
        self.assertEqual(LW.settings("qwen3:14b")["model"], "qwen3:14b")      # an explicit flag wins

    def test_context_is_kept_between_4k_and_6k(self):
        self.assertEqual(LW.settings()["num_ctx"], 4096)
        self.assertEqual(LW.clamp_ctx(12288), 6144)
        self.assertEqual(LW.clamp_ctx(512), 4096)
        self.assertEqual(LW.clamp_ctx("5000"), 5000)
        self.assertEqual(LW.clamp_ctx("junk"), 4096)

    def test_no_900_second_hard_timeout(self):
        s = LW.settings()
        self.assertNotEqual(s["first_token_s"], 900)
        self.assertLess(s["wait_s"], 30)                      # the watcher itself never waits long on Lumo

    def test_the_chat_model_is_not_the_watch_model(self):
        self.assertNotIn("LUMO_CHAT_MODEL", LW.__doc__.split("Interactive Q&A")[0])


class TestPayload(Base):
    def test_payload_is_chat_think_false_stream_true_small_context(self):
        _, msgs = self.messages()
        p = LW.chat_payload(msgs, self.cfg)
        self.assertIs(p["think"], False)
        self.assertIs(p["stream"], True)
        self.assertEqual(p["model"], "qwen3:4b")
        self.assertTrue(4096 <= p["options"]["num_ctx"] <= 6144)
        self.assertEqual(p["messages"][0]["role"], "system")
        self.assertNotIn("prompt", p)                          # /api/chat messages, not /api/generate prompt
        self.assertNotIn("/no_think", json.dumps(p))

    def test_request_on_the_wire(self):
        m = self.mock()
        _, msgs = self.messages()
        out = os.path.join(self.root, "o.md")
        LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], out, idle_s=2)
        self.assertEqual(m.paths, ["/api/chat"])
        req = m.requests[0]
        self.assertIs(req["think"], False)
        self.assertIs(req["stream"], True)
        self.assertEqual(req["options"]["num_ctx"], 4096)
        self.assertIn("Nick's standing rules", req["messages"][0]["content"])


class TestStreaming(Base):
    def test_stream_is_parsed_and_saved(self):
        self.mock([("piece", "- Height "), ("piece", "differs by 2 ft.\n"), ("piece", "Verdict: WATCH"), ("done",)])
        out, st_path = os.path.join(self.root, "o.md"), os.path.join(self.root, "o.status.json")
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], out, st_path, idle_s=2, header="<!-- h -->\n")
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["text"], "- Height differs by 2 ft.\nVerdict: WATCH")
        self.assertEqual(slurp(out), "<!-- h -->\n- Height differs by 2 ft.\nVerdict: WATCH")
        self.assertEqual(jload(st_path)["status"], "done")
        self.assertEqual((st["prompt_eval_count"], st["eval_count"]), (700, 120))

    def test_each_piece_is_on_disk_before_the_stream_ends(self):
        gate = threading.Event()
        self.mock([("piece", "first piece"), ("wait_event", gate), ("piece", " second"), ("done",)])
        out = os.path.join(self.root, "o.md")
        _, msgs = self.messages()
        res = {}
        t = threading.Thread(target=lambda: res.update(LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], out,
                                                                      idle_s=8)))
        t.start()
        deadline = time.time() + 5
        while time.time() < deadline and not (os.path.exists(out) and "first piece" in slurp(out)):
            time.sleep(0.05)
        self.assertIn("first piece", slurp(out))         # on disk while the model is still "generating"
        self.assertNotIn("second", slurp(out))
        gate.set()
        t.join(10)
        self.assertEqual(res["status"], "done")

    def test_idle_timeout_keeps_the_partial_text(self):
        self.mock([("piece", "partial answer"), ("wait", 3.0), ("piece", " never read"), ("done",)])
        self.cfg["idle_s"] = 0.5
        out = os.path.join(self.root, "o.md")
        _, msgs = self.messages()
        t0 = time.time()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], out, idle_s=0.5)
        self.assertLess(time.time() - t0, 2.5)
        self.assertEqual(st["status"], "partial")
        self.assertEqual(slurp(out), "partial answer")
        self.assertIn("partial text kept", st["error"])

    def test_dropped_connection_keeps_the_partial_text(self):
        self.mock([("piece", "cut off"), ("drop",)])
        out = os.path.join(self.root, "o.md")
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], out, idle_s=2)
        self.assertEqual(st["status"], "partial")
        self.assertEqual(slurp(out), "cut off")

    def test_deadline_stops_the_wait_not_the_text(self):
        self.mock([("piece", "a"), ("wait", 0.4), ("piece", "b"), ("wait", 0.4), ("piece", "c"), ("done",)])
        out = os.path.join(self.root, "o.md")
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], out, idle_s=2, deadline_s=0.3)
        self.assertEqual(st["status"], "partial")
        self.assertTrue(slurp(out).startswith("a"))

    def test_bad_lines_are_skipped(self):
        self.mock([("raw", "not json\n"), ("piece", "fine"), ("done",)])
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], os.path.join(self.root, "o.md"), idle_s=2)
        self.assertEqual((st["status"], st["text"]), ("done", "fine"))

    def test_thinking_field_is_not_saved(self):
        self.mock([("raw", json.dumps({"message": {"role": "assistant", "content": "", "thinking": "secret chain"},
                                       "done": False}) + "\n"), ("piece", "answer"), ("done",)])
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], os.path.join(self.root, "o.md"), idle_s=2)
        self.assertEqual(st["text"], "answer")

    def test_server_error_in_the_stream(self):
        self.mock([("raw", json.dumps({"error": "model not found"}) + "\n")])
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], os.path.join(self.root, "o.md"), idle_s=2)
        self.assertEqual(st["status"], "error")
        self.assertIn("model not found", st["error"])

    def test_http_error(self):
        self.mock(status=500, body="internal")
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], os.path.join(self.root, "o.md"), idle_s=2)
        self.assertEqual(st["status"], "error")
        self.assertIn("500", st["error"])

    def test_ollama_not_running_is_a_status_not_an_exception(self):
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), free_port_url(), os.path.join(self.root, "o.md"), idle_s=2)
        self.assertEqual(st["status"], "unavailable")
        self.assertIn("stand without Lumo", st["error"])

    def test_model_without_a_thinking_switch_is_retried_without_think(self):
        m = self.mock([("piece", "phi answer"), ("done",)])
        m.fail_think_400 = True
        self.cfg["model"] = "phi4-mini"
        _, msgs = self.messages()
        st = LW.stream_chat(LW.chat_payload(msgs, self.cfg), self.cfg["url"], os.path.join(self.root, "o.md"), idle_s=2)
        self.assertEqual((st["status"], st["text"]), ("done", "phi answer"))
        self.assertIn("think", m.requests[0])
        self.assertNotIn("think", m.requests[1])


class TestPrompt(Base):
    def test_user_prompt_is_short(self):
        run, dam = FX.make_run(self.root, hazard=True, unscored_roads=11, mass_nan=True, final_leak=True)
        d = RD.build_digest(run, dam_folder=dam, points_path=FX.write_points(self.root))
        u = LW.build_user_prompt(d, "run_end")
        self.assertLess(LW.est_tokens(u), 1000)
        self.assertGreater(LW.est_tokens(u), 100)
        self.assertIn("VERDICT (set by code, do not change): PROBLEM", u)
        self.assertTrue(u.rstrip().endswith("Verdict: PROBLEM"))

    def test_prompt_is_trimmed_to_the_budget(self):
        run, dam = FX.make_run(self.root)
        d = RD.build_digest(run, dam_folder=dam)
        small = LW.build_user_prompt(d, "run_end", max_tokens=150)
        self.assertLess(LW.est_tokens(small), LW.est_tokens(LW.build_user_prompt(d, "run_end")))
        self.assertIn("FLAGS", small)

    def test_whole_request_fits_a_4k_context(self):
        _, msgs = self.messages()
        total = LW.est_tokens(msgs[0]["content"]) + LW.est_tokens(msgs[1]["content"])
        self.assertLess(total + self.cfg["num_predict"], 4096)

    def test_prompt_carries_the_flags_not_the_raw_log(self):
        d, msgs = self.messages()
        u = msgs[1]["content"]
        self.assertIn("HEIGHT_MISMATCH", u)
        self.assertNotIn("Tstep", u)                          # no .mass dump

    def test_info_flags_are_not_in_the_prompt(self):
        d = {"verdict": "OK", "phase": "run_end", "text": "x", "flags": [
            {"id": "RUN_WARNINGS", "severity": "INFO", "where": "run", "title": "note"}]}
        self.assertIn("none", LW.build_user_prompt(d))


class TestSystemPrompt(StrictCase):
    def test_pinned_rules(self):
        s = LW.system_prompt()
        for needle in ("NO inflow and NO outlet or spillway flow", "top of dam, which is the DWR max pool",
                       "NAVD88 only", "0-300 ft is a local datum", "H x (downstream slope + 1)", "3:1", "150 m",
                       "BNSF KO subdivision = 15 trains per day", "judgment zone as Medium", "maxima over wet cells",
                       "EXPECTED while the domain grows", "not dam leakage", "model domain edge", "only flag ids are", "UNSURE", "Verdict:"):
            self.assertIn(needle, s)

    def test_the_rule_lumo_reversed_is_stated_the_right_way_round(self):
        s = LW.system_prompt()
        self.assertNotRegex(s, r"(?i)inflow equal to")
        self.assertNotRegex(s, r"(?i)outlets? (fully )?operational")
        self.assertNotIn("max pool is the lower", s)

    def test_mirror_file_is_in_step(self):
        p = os.path.join(LUMO, "prompts", "watcher_system.md")
        self.assertEqual(slurp(p).rstrip("\n"), LW.system_prompt())

    def test_real_ids_and_parameters_only(self):
        """Every tool id, CELL-style parameter and switch the prompt names must exist in the generated dump of the
        real algorithms (ALGORITHM-HELP-DAMIT.md), and the invented names must not appear."""
        help_md = slurp(os.path.join(LUMO, "knowledge", "ALGORITHM-HELP-DAMIT.md"))
        s = LW.system_prompt()
        for tid in ("damit_screen:handoff", "damit_run:rundam", "damit:classify", "damit_lite:classify"):
            self.assertIn("### `%s`" % tid, help_md)
            self.assertIn(tid, s)
        listed = re.search(r"parameters include ([A-Z_, ]+)\.", s).group(1).split(", ")
        for prm in listed:
            self.assertIn("| `%s` |" % prm.strip(), help_md, prm)
        self.assertIn("RAIL_TRAINS_LOOKUP", help_md)
        self.assertIn("--GRID_REFINE=0", s)
        for bad in ("damit_runner", "--no-refine", "damit_screener_handoff", "damit_hazard_classification"):
            self.assertNotIn(bad, s.replace("(no others exist)", ""))


class TestHooks(Base):
    def run_fx(self, **kw):
        run, dam = FX.make_run(self.root, **kw)
        return run, dam

    def test_event_writes_the_digest_and_returns_without_waiting_for_lumo(self):
        run, dam = self.run_fx()
        out = os.path.join(self.root, "watch")
        spawned = []
        t0 = time.time()
        self.cfg["wait_s"] = 0.4
        r = LW.run_event(run, "run_end", out, lumo=True, cfg=self.cfg, spawn=lambda jp, cfg: spawned.append(jp),
                         dam_folder=dam)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(r["verdict"], "WATCH")
        self.assertEqual(r["lumo"]["status"], "pending")            # Lumo never answered; the review stands
        self.assertEqual(len(spawned), 1)
        self.assertTrue(os.path.exists(os.path.join(out, "digest_run_end.json")))
        self.assertTrue(os.path.exists(os.path.join(out, "digest_run_end.txt")))
        self.assertEqual(jload(os.path.join(out, "latest_verdict.json"))["verdict"], "WATCH")

    def test_verdict_is_identical_with_and_without_lumo(self):
        run, dam = self.run_fx(mass_nan=True)
        a = LW.run_event(run, "run_end", os.path.join(self.root, "a"), lumo=False, cfg=self.cfg, dam_folder=dam)
        b = LW.run_event(run, "run_end", os.path.join(self.root, "b"), lumo=True, cfg=self.cfg, spawn=lambda *x: None,
                         dam_folder=dam)
        self.assertEqual(a["verdict"], b["verdict"])
        self.assertEqual([f["id"] for f in a["digest"]["flags"]], [f["id"] for f in b["digest"]["flags"]])
        self.assertIsNone(a["lumo"])

    def test_lumo_text_never_changes_the_saved_digest(self):
        run, dam = self.run_fx()
        m = self.mock([("piece", "Everything is fine, verdict OK."), ("done",)])
        r = LW.run_event(run, "run_end", os.path.join(self.root, "w"), lumo=False, cfg=self.cfg, dam_folder=dam)
        before = slurp(r["digest_path"])
        st = LW.explain(r["digest_path"], self.cfg)
        self.assertEqual(st["status"], "done")
        self.assertEqual(slurp(r["digest_path"]), before)
        self.assertEqual(jload(r["digest_path"])["verdict"], "WATCH")
        md = slurp(os.path.join(os.path.dirname(r["digest_path"]), "lumo_run_end.md"))
        self.assertIn("does not set or change it", md)
        self.assertIn("verdict OK", md)                      # Lumo's words are kept as written, the verdict is not
        self.assertEqual(m.paths, ["/api/chat"])
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(r["digest_path"]), "lumo.busy")))

    def test_event_with_a_real_background_process_and_the_mock_server(self):
        run, dam = self.run_fx()
        self.addCleanup(LW.reap_children, 10)
        self.mock([("piece", "- Height 37 vs 39 ft.\n"), ("piece", "Verdict: WATCH"), ("done",)])
        self.cfg["wait_s"] = 20
        r = LW.run_event(run, "run_end", os.path.join(self.root, "w"), lumo=True, cfg=self.cfg, dam_folder=dam)
        self.assertEqual(r["lumo"]["status"], "done")
        md = slurp(os.path.join(r["out_dir"], "lumo_run_end.md"))
        self.assertIn("Height 37 vs 39 ft", md)

    def test_unknown_event_and_run_folder_output_are_refused(self):
        run, dam = self.run_fx()
        with self.assertRaises(ValueError):
            LW.run_event(run, "nonsense", os.path.join(self.root, "w"))
        with self.assertRaises(ValueError):
            LW.run_event(run, "run_end", os.path.join(run, "watch"), lumo=False, dam_folder=dam)
        self.assertFalse(os.path.exists(os.path.join(run, "watch")))

    def test_a_busy_lumo_is_skipped_not_queued(self):
        run, dam = self.run_fx()
        out = os.path.join(self.root, "w")
        os.makedirs(out)
        spit(os.path.join(out, "lumo.busy"), str(os.getpid()))
        r = LW.run_event(run, "run_end", out, lumo=True, cfg=self.cfg, spawn=lambda *a: self.fail("spawned"), dam_folder=dam)
        self.assertEqual(r["lumo"]["status"], "skipped")
        self.assertEqual(r["verdict"], "WATCH")


class TestEventDetector(Base):
    def test_a_finished_run_fires_every_hook_in_one_scan(self):
        run, dam = FX.make_run(self.root)
        # the dam folder is the fixture's run_setup dam_folder (no classify report yet)
        det, state = LW.EventDetector(), {}
        ev = det.scan(run, state)
        self.assertEqual([e["event"] for e in ev], ["pass_end", "pass_end", "pass_end", "run_end", "before_hazard"])
        self.assertEqual([e["pass"] for e in ev[:3]], [1, 2, 3])
        self.assertEqual(det.scan(run, state), [])                    # nothing fires twice

    def test_after_hazard_fires_when_the_report_appears(self):
        run, dam = FX.make_run(self.root)
        det, state = LW.EventDetector(), {}
        det.scan(run, state)
        FX.make_run(self.root, hazard=True)
        self.assertEqual([e["event"] for e in det.scan(run, state)], ["after_hazard"])

    def test_before_hazard_is_not_fired_when_hazard_already_ran(self):
        run, dam = FX.make_run(self.root, hazard=True)
        ev = [e["event"] for e in LW.EventDetector().scan(run, {})]
        self.assertNotIn("before_hazard", ev)
        self.assertIn("after_hazard", ev)

    def test_stall_hook(self):
        run, dam = FX.make_run(self.root, unfinished=True, report=False)
        os.remove(os.path.join(run, "run_setup.json"))              # a run still in progress has no setup status yet
        write = FX.write
        write(os.path.join(run, "run_setup.json"), json.dumps({"status": "running", "dam_folder": dam}))
        mp = os.path.join(run, "model", "run03_50m", "results", "run.mass")
        t = os.path.getmtime(mp)
        det, state = LW.EventDetector(stall_s=900), {}
        ev = det.scan(run, state, now=t + 100)
        self.assertEqual([e["event"] for e in ev], ["pass_end", "pass_end"])      # passes 1-2 done, pass 3 running
        ev = det.scan(run, state, now=t + 1000)
        self.assertEqual([(e["event"], e["pass"]) for e in ev], [("stall", 3)])
        self.assertEqual(det.scan(run, state, now=t + 2000), [])

    def test_pass_end_digest_covers_only_the_passes_so_far(self):
        run, dam = FX.make_run(self.root)
        r = LW.run_event(run, "pass_end", os.path.join(self.root, "w"), pass_no=1, lumo=False, dam_folder=dam)
        self.assertEqual(len(r["digest"]["checks"]["passes"]), 1)
        self.assertEqual(os.path.basename(r["digest_path"]), "digest_pass_end_p1.json")

    def test_a_leaking_newest_pass_is_not_called_final_while_the_run_is_in_progress(self):
        run, dam = FX.make_run(self.root)
        r = LW.run_event(run, "pass_end", os.path.join(self.root, "w"), pass_no=2, lumo=False, dam_folder=dam)
        ids = [f["id"] for f in r["digest"]["flags"]]
        self.assertNotIn("EDGE_OUTFLOW_FINAL", ids)
        self.assertEqual(ids.count("EDGE_OUTFLOW_EARLY"), 2)
        self.assertEqual(r["verdict"], "WATCH")
        self.assertIsNone(r["digest"]["checks"]["hazard"])           # no Hazard in a pass digest

    def test_a_45_second_run_is_still_reviewed_at_every_hook(self):
        run, dam = FX.make_run(self.root)                               # everything is already on disk when we look
        spawns = []
        res = LW.watch(run, os.path.join(self.root, "w"), until="before_hazard", lumo=True, cfg=self.cfg, once=True,
                       log=lambda *a: None, spawn=lambda jp, cfg: spawns.append(jp))
        self.assertEqual([r["event"] for r in res], ["pass_end", "pass_end", "pass_end", "run_end", "before_hazard"])
        self.assertTrue(all(r["verdict"] in ("OK", "WATCH", "PROBLEM") for r in res))
        self.assertEqual(len(spawns), 1)                                # one inference for the burst: the newest event
        self.assertTrue(spawns[0].endswith("digest_before_hazard.json"))
        self.assertEqual(len(os.listdir(os.path.join(self.root, "w"))) >= 11, True)

    def test_watch_stops_after_the_until_event(self):
        run, dam = FX.make_run(self.root)
        t0 = time.time()
        res = LW.watch(run, os.path.join(self.root, "w"), poll_s=0.05, until="run_end", lumo=False, cfg=self.cfg,
                       max_wait_s=5, log=lambda *a: None)
        self.assertLess(time.time() - t0, 2)
        self.assertIn("run_end", [r["event"] for r in res])


class TestCli(Base):
    def test_digest_and_event_commands(self):
        import contextlib
        import io
        run, dam = FX.make_run(self.root)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = LW.main(["digest", run, "--dam-folder", dam, "--json", "--exit-code"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(buf.getvalue())["verdict"], "WATCH")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = LW.main(["event", "run_end", run, "--dam-folder", dam, "--no-lumo", "--out", os.path.join(self.root, "o")])
        self.assertEqual(rc, 0)
        self.assertIn("Lumo: not asked", buf.getvalue())

    def test_prompt_command_shows_the_size(self):
        import contextlib
        import io
        run, dam = FX.make_run(self.root)
        r = LW.run_event(run, "run_end", os.path.join(self.root, "w"), lumo=False, dam_folder=dam)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            LW.main(["prompt", r["digest_path"]])
        self.assertRegex(buf.getvalue(), r"\[system ~\d+ tokens \+ user ~\d+ tokens\]")


if __name__ == "__main__":
    unittest.main()
