"""The interactive Q&A persona (`heim`, `heim-chat`) carries Nick's standing rules and the real tool ids.

The 11 Nov 2026 install test (qwen3:8b) asked the persona directly, with no retrieval, and it reversed the sunny-day
rule ("inflow equals reservoir capacity, outlets fully operational") and invented algorithm names
(damit_screener_handoff, damit_runner, damit_hazard_classification, --no-refine). The knowledge pack already had the
right answers, but `heim-chat` is a bare `ollama run heim`: it never reads the pack. The run watcher's prompt had
the rules; the Q&A persona's SYSTEM prompt did not. These tests keep the rules in every installer's persona and make
the eval able to catch the 11 Nov answers on the persona-only path (eval_heim.py --no-context).

Pure Python; the eval test runs eval_heim.py against a local fake Ollama (no model, no network)."""
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
HEIM = os.path.abspath(os.path.join(HERE, ".."))
AI = os.path.abspath(os.path.join(HEIM, ".."))
sys.path.insert(0, os.path.join(HEIM, "tools"))
sys.path.insert(0, HERE)
from strict import StrictCase, slurp  # noqa: E402
import eval_heim as EP  # noqa: E402

RULES_FILE = os.path.join(HEIM, "prompts", "persona_rules.txt")
INSTALLERS = (os.path.join(AI, "install-local-ai-linux.sh"),
              os.path.join(AI, "install-local-ai-windows.ps1"),
              os.path.join(HEIM, "setup-local-heim.sh"))
REAL_IDS = ("damit_screen:handoff", "damit_run:rundam", "damit:classify", "damit_lite:classify")
FAKE_NAMES = ("damit_screener_handoff", "damit_runner", "damit_hazard_classification", "--no-refine")

# What qwen3:8b answered on 11 Nov 2026 (DWR-2658 install test, as recorded in the test report).
WRONG_SUNNY = ("A sunny-day breach assumes normal weather. The inflow equals the reservoir capacity and the outlets "
               "are fully operational, so the spillway passes the routine flow.")
WRONG_TOOLS = ("Run damit_screener_handoff, then damit_runner, then damit_hazard_classification. "
               "Pass --no-refine to skip the 10 m refine.")
RIGHT_SUNNY = ("On a sunny day the reservoir starts at the top of dam, the DWR max pool. There is no inflow, the outlets "
               "are empty, and there is no outlet or spillway flow; the only water is the breach. It is not true that "
               "the inflow equals the reservoir capacity.")
RIGHT_TOOLS = ("Use damit_screen:handoff, then damit_run:rundam, then damit:classify. Turn the refine off with "
               "--GRID_REFINE=0. There is no --no-refine switch and no damit_runner algorithm; "
               "damit_screener_handoff does not exist.")


def rules():
    return slurp(RULES_FILE).rstrip("\n")


def persona_system(path):
    t = slurp(path)
    i = t.index('SYSTEM """You are Heim-Lite')
    return t[i:t.index('"""', i + 10)]


def question(qid):
    return next(q for q in json.loads(slurp(os.path.join(HEIM, "eval", "questions.json")))["questions"]
                if q["id"] == qid)


class TestPersonaRules(StrictCase):
    def test_the_rules_state_the_sunny_day_rule_the_right_way_round(self):
        r = rules()
        for needle in ("NO inflow", "outlets are empty", "NO outlet or spillway flow", "top of dam",
                       "DWR max pool", "storage at the pool when the breach starts"):
            self.assertIn(needle, r)
        self.assertNotRegex(r, r"(?i)sunny[^.\n]{0,60}(inflow equal|outlets? (are )?operational)")

    def test_the_rules_name_only_real_ids_and_reject_the_invented_ones(self):
        r = rules()
        helpdoc = slurp(os.path.join(HEIM, "knowledge", "ALGORITHM-HELP-DAMIT.md"))
        for tid in REAL_IDS:
            self.assertIn(tid, r)
            self.assertIn("### `%s`" % tid, helpdoc)              # exists in the dump generated from the code
        self.assertIn("--GRID_REFINE=0", r)
        self.assertRegex(helpdoc, r"\| `GRID_REFINE` \|")
        for name in FAKE_NAMES:
            self.assertRegex(r, r"no %s\b" % re.escape(name))       # named only to say it does not exist
            self.assertNotIn("### `%s`" % name, helpdoc)
        for tid in set(re.findall(r"\bdamit[a-z_]*:[a-z0-9]+", r)):  # every id-shaped name in the rules is real
            self.assertIn("### `%s`" % tid, helpdoc, tid)

    def test_the_rules_survive_every_installer_quoting(self):
        """Linux / Mac write the Modelfile with an unquoted heredoc, Windows with a @"..."@ here-string: a $, a
        backtick or a backslash would be expanded, and a triple quote would end the SYSTEM block."""
        r = rules()
        self.assertNotRegex(r, r'[$`\\]')
        self.assertNotIn('"""', r)
        self.assertNotIn('"@', r)

    def test_every_installer_persona_carries_the_rules(self):
        r = rules()
        for path in INSTALLERS:
            self.assertIn(r, persona_system(path), os.path.basename(path))


class TestEvalCatchesTheElevenNovAnswers(StrictCase):
    def test_the_recorded_wrong_answers_fail(self):
        ok, _, bad = EP.score(WRONG_SUNNY, question("sunny-day-rule"))
        self.assertFalse(ok)
        self.assertTrue(bad)                                    # caught as forbidden, not only as missing facts
        ok, _, bad = EP.score(WRONG_TOOLS, question("real-tool-names"))
        self.assertFalse(ok)
        self.assertEqual(len(bad), 4, bad)                      # all four invented names

    def test_right_answers_pass_even_when_they_name_the_fakes_to_reject_them(self):
        for ans, qid in ((RIGHT_SUNNY, "sunny-day-rule"), (RIGHT_TOOLS, "real-tool-names")):
            ok, miss, bad = EP.score(ans, question(qid))
            self.assertTrue(ok, (qid, miss, bad))

    def test_no_refine_is_not_its_own_negation(self):
        self.assertTrue(EP.forbidden_hits("Use --no-refine for speed.", question("real-tool-names")))

    def test_a_plugin_folder_path_is_not_an_invented_tool(self):
        self.assertFalse(EP.forbidden_hits("The code is in damit_runner/flood/model.py.", question("real-tool-names")))


class _FakeOllama(http.server.BaseHTTPRequestHandler):
    answers = {}
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][-1]["content"]
        type(self).seen.append(body)
        ans = next((a for k, a in self.answers.items() if k in prompt), "UNSURE")
        out = json.dumps({"message": {"role": "assistant", "content": ans}, "done": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class TestEvalNoContext(StrictCase):
    """eval_heim.py --no-context asks the persona the bare question (the heim-chat path) and scores it."""

    def run_eval(self, answers):
        _FakeOllama.answers, _FakeOllama.seen = answers, []
        srv = http.server.HTTPServer(("127.0.0.1", 0), _FakeOllama)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        rep = tempfile.mkdtemp(prefix="heim_eval_")
        try:
            env = dict(os.environ, OLLAMA_URL="http://127.0.0.1:%d" % srv.server_port, HEIM_REPORTS=rep,
                       HEIM_DB=os.path.join(rep, "absent.db"))
            r = subprocess.run([sys.executable, os.path.join(HEIM, "tools", "eval_heim.py"), "--no-context",
                                "--only", "sunny-day-rule,real-tool-names", "--model", "heim"],
                               capture_output=True, text=True, env=env, timeout=120)
            files = [f for f in os.listdir(rep) if f.endswith(".json")]
            self.assertEqual(len(files), 1, r.stdout + r.stderr)
            self.assertIn("_nocontext_", files[0])
            with open(os.path.join(rep, files[0]), encoding="utf-8") as f:
                rows = {x["id"]: x for x in json.load(f)["rows"]}
            return r, rows
        finally:
            srv.shutdown()
            srv.server_close()
            th.join(5)
            import shutil
            shutil.rmtree(rep, True)

    def test_the_eleven_nov_answers_fail_the_persona_eval(self):
        r, rows = self.run_eval({"sunny-day rule": WRONG_SUNNY, "algorithm ids": WRONG_TOOLS})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual({k: v["result"] for k, v in rows.items()},
                         {"sunny-day-rule": "fail", "real-tool-names": "fail"})
        for body in _FakeOllama.seen:                           # the bare question, no retrieved context
            self.assertNotIn("=== CONTEXT ===", body["messages"][-1]["content"])
            self.assertEqual(body["model"], "heim")

    def test_correct_answers_pass_the_persona_eval(self):
        r, rows = self.run_eval({"sunny-day rule": RIGHT_SUNNY, "algorithm ids": RIGHT_TOOLS})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual({v["result"] for v in rows.values()}, {"pass"})
