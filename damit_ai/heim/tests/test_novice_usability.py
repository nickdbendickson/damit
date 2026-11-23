"""Novice usability (2026-11-23, Nick: "Do small ones and 2-8").

What a first-time user hit, each pinned here:
  - a Python traceback when Ollama was not running or a model was missing (now one plain line);
  - `heim` on its own said "no question given", `vor` on its own an argparse error (now the short list);
  - `vor what breach width ...` was an error (now `vor ask`);
  - `heim run add FOLDER` / `heim runs "run 2801 ..."` mixed up (now "did you mean");
  - the `ai` page sent a question about a standard to Heim (now: Vor unless it is about this software);
  - heim run asked the model before saying the dams layer was missing, and a refusal left the user
    with nothing to type (now: the paths first, and a damchain line to type);
  - damchain said "conda not found" before saying the dams layer path was wrong (now the path first);
  - after a run, nothing said where the results were or how to ask about them;
  - ai-doctor gave no versions and said nothing about damchain;
  - the installers ended with developer hints, and stopped without saying how to carry on.

No Ollama, no QGIS, no conda: everything they would answer is stubbed.
"""
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HEIM = os.path.dirname(HERE)
TOOLS = os.path.join(HEIM, "tools")
AI = os.path.dirname(HEIM)
VOR = os.path.join(AI, "vor", "vor.py")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RQ = load("rq_novice", os.path.join(TOOLS, "rag_query.py"))
RR = load("rr_novice", os.path.join(TOOLS, "run_results.py"))
HR = load("hr_novice", os.path.join(TOOLS, "heim_run.py"))
DC = load("dc_novice", os.path.join(TOOLS, "dam_chain.py"))


def http_error(code, body):
    return urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", code, "x", {}, io.BytesIO(body.encode()))


def source(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def function_text(src, name):
    m = re.search(r"^def %s\(.*?(?=^\S)" % name, src, re.S | re.M)
    return m.group(0).rstrip() if m else None


class OllamaProblemTest(unittest.TestCase):
    """Item 3: one plain line for each way a call to Ollama fails."""

    def test_not_running(self):
        msg = RQ.ollama_problem(urllib.error.URLError(ConnectionRefusedError(111, "refused")))
        self.assertIn("Ollama is not answering at", msg)
        self.assertIn("then try again", msg)
        self.assertIn("ollama serve" if sys.platform != "darwin" else "heim-start", msg)

    def test_a_missing_persona_says_run_the_installer(self):
        msg = RQ.ollama_problem(http_error(404, json.dumps({"error": 'model "heim" not found, try pulling it first'})))
        self.assertIn("no model heim", msg)
        self.assertIn("run the installer again", msg)
        self.assertNotIn("ollama pull heim", msg)          # heim is made by the installer, not pulled

    def test_a_missing_pulled_model_says_ollama_pull(self):
        msg = RQ.ollama_problem(http_error(404, json.dumps({"error": "model 'nomic-embed-text' not found"})))
        self.assertIn("ollama pull nomic-embed-text", msg)

    def test_timeouts_and_errors_inside_an_answer(self):
        self.assertIn("took too long", RQ.ollama_problem(socket.timeout("timed out")))
        self.assertIn("took too long", RQ.ollama_problem(urllib.error.URLError(socket.timeout("timed out"))))
        self.assertIn("out of memory", RQ.ollama_problem(RQ.OllamaError("out of memory")))
        self.assertIn("HTTP 500", RQ.ollama_problem(http_error(500, "boom")))

    def test_anything_else_is_a_real_bug_and_keeps_its_traceback(self):
        for e in (ValueError("x"), KeyError("y"), BrokenPipeError(32, "pipe"), RuntimeError("other")):
            self.assertIsNone(RQ.ollama_problem(e), e)

    def test_the_copies_are_identical(self):
        rq, rr = source(os.path.join(TOOLS, "rag_query.py")), source(os.path.join(TOOLS, "run_results.py"))
        for name in ("ollama_problem", "start_hint"):
            self.assertIsNotNone(function_text(rq, name), name)
            self.assertEqual(function_text(rq, name), function_text(rr, name), name)
        hint = function_text(rq, "start_hint")
        for path in (os.path.join(TOOLS, "rag_index.py"), VOR):
            self.assertEqual(function_text(source(path), "start_hint"), hint, path)

    def test_heim_prints_one_line_and_exits_1(self):
        def down(*a, **k):
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        keep = (RQ.retrieve, RQ.run_question, sys.argv)
        RQ.retrieve, RQ.run_question, sys.argv = down, (lambda q: []), ["heim", "what does REFINE_NEAR do"]
        err, out = io.StringIO(), io.StringIO()
        try:
            with redirect_stderr(err), redirect_stdout(out), self.assertRaises(SystemExit) as cm:
                RQ.main()
        finally:
            RQ.retrieve, RQ.run_question, sys.argv = keep
        self.assertEqual(cm.exception.code, 1)
        self.assertTrue(err.getvalue().startswith("heim: Ollama is not answering"), err.getvalue())
        self.assertNotIn("Traceback", err.getvalue() + out.getvalue())

    def test_heim_debug_keeps_the_traceback(self):
        def down(*a, **k):
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        keep = (RQ.retrieve, RQ.run_question, sys.argv)
        RQ.retrieve, RQ.run_question, sys.argv = down, (lambda q: []), ["heim", "q"]
        os.environ["HEIM_DEBUG"] = "1"
        try:
            with redirect_stdout(io.StringIO()), self.assertRaises(urllib.error.URLError):
                RQ.main()
        finally:
            os.environ.pop("HEIM_DEBUG", None)
            RQ.retrieve, RQ.run_question, sys.argv = keep


class BareCommandTest(unittest.TestCase):
    """Item 5: a bare command prints the short list; the commands are named as installed."""

    def run_tool(self, path, *args, env=None):
        e = dict(os.environ, HOME=tempfile.mkdtemp(prefix="bare-"), HEIM_DB="/nonexistent/k.db", **(env or {}))
        try:
            return subprocess.run([sys.executable, path] + list(args), capture_output=True, text=True, env=e,
                                  timeout=60)
        finally:
            shutil.rmtree(e["HOME"], ignore_errors=True)

    def test_heim_on_its_own(self):
        for args in ((), ("help",)):
            p = self.run_tool(os.path.join(TOOLS, "rag_query.py"), *args)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("The commands you will use", p.stdout)
            self.assertNotIn("no question given", p.stdout + p.stderr)

    def test_vor_on_its_own_and_vor_words_is_vor_ask(self):
        p = self.run_tool(VOR, env={"VOR_HOME": tempfile.mkdtemp(prefix="vor-bare-")})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('vor "question"', p.stdout)
        self.assertNotIn("required", p.stderr)
        vor = load("vor_novice", VOR)
        seen = []
        vor.cmd_ask = lambda a: seen.append((a.cmd, " ".join(a.question)))
        keep = sys.argv
        sys.argv = ["vor", "what", "breach", "width", "does", "Froehlich", "give?"]
        try:
            vor.main()
        finally:
            sys.argv = keep
        self.assertEqual(seen, [("ask", "what breach width does Froehlich give?")])

    def test_the_parsers_carry_the_command_names(self):
        for f, prog in (("rag_query.py", 'prog="heim"'), ("rag_index.py", 'prog="heim-index"'),
                        ("dam_chain.py", 'prog="damchain"'), ("heim_watch.py", 'prog="heim-watch"'),
                        ("run_digest.py", 'prog="heim-digest"')):
            self.assertIn(prog, source(os.path.join(TOOLS, f)), f)
        for f in ("rag_query.py", "rag_index.py", "run_results.py"):
            self.assertNotIn("heim-start\n", source(os.path.join(TOOLS, f)))
        self.assertNotIn("Start it: heim-start", source(os.path.join(TOOLS, "rag_index.py")))
        self.assertNotIn("(is Ollama running? heim-start)", source(os.path.join(TOOLS, "rag_query.py")))


class RunOrRunsTest(unittest.TestCase):
    """Small item: `heim run` (draft a model run) and `heim runs` (read results) one letter apart."""

    def test_heim_run_add_folder_points_to_heim_runs(self):
        with self.assertRaises(SystemExit) as cm:
            RQ.command_word(["run", "add", "/tmp/Dams"])
        self.assertIn("Did you mean:  heim runs add /tmp/Dams", str(cm.exception.code))
        for word in ("show", "list", "compare", "hydrograph"):
            with self.assertRaises(SystemExit):
                RQ.command_word(["run", word, "2801"])
        # still run requests
        self.assertEqual(RQ.command_word(["run", "2801 at 5 m"])[0], "heimrun")
        self.assertEqual(RQ.command_word(["run", "at 5 m 2801"])[0], "heimrun")
        self.assertEqual(RQ.command_word(["run", "--show", "2801"])[0], "heimrun")

    def test_heim_runs_with_a_run_request_points_to_heim_run(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = RR.main(["run 2801 at 5 m"])
        self.assertEqual(code, 2)
        self.assertIn("heim runs does not know", out.getvalue())
        self.assertIn("heim run 'run 2801 at 5 m'", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            RR.main(["frobnicate"])
        self.assertNotIn("heim run '", out.getvalue())

    def test_db_value_is_not_taken_for_a_command(self):
        tmp = tempfile.mkdtemp(prefix="rr-db-")
        keep = RR.DB
        try:
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
                RR.main(["--db", os.path.join(tmp, "r.db"), "list"])
            self.assertNotIn("does not know", out.getvalue())
            self.assertIn("No run results yet", str(cm.exception.code))      # `list` ran
        finally:
            RR.DB = keep
            shutil.rmtree(tmp, ignore_errors=True)


class HeimRunNoviceTest(unittest.TestCase):
    """Small items: paths before the model; a refusal ends with a command to type."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="heim-run-novice-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        HR.SAVED = os.path.join(self.tmp, "heim_run.json")
        self.dams = os.path.join(self.tmp, "dams.gpkg")
        con = sqlite3.connect(self.dams)
        con.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
        con.execute("INSERT INTO gpkg_contents VALUES ('dams', 'features')")
        con.execute("CREATE TABLE dams (fid INTEGER PRIMARY KEY, dam_id TEXT)")
        con.execute("INSERT INTO dams (dam_id) VALUES ('2801')")
        con.commit()
        con.close()
        self.dem = os.path.join(self.tmp, "dem.tif")
        open(self.dem, "w").close()
        self.asked = []

    def go(self, argv, reply):
        said = []

        def chat(messages, fmt=None, timeout=None):
            self.asked.append(messages)
            if isinstance(reply, Exception):
                raise reply
            return json.dumps(reply)
        code = HR.main(argv, chat=chat, ask=lambda p: "n", runner=lambda a: 0, out=said.append)
        return code, "\n".join(said)

    def test_a_missing_path_is_said_before_the_model_is_asked(self):
        code, said = self.go(["--set", "damit", "--dams", os.path.join(self.tmp, "nope.gpkg"), "--out",
                              os.path.join(self.tmp, "runs"), "--dem", self.dem, "run 2801"], {"ids": ["2801"]})
        self.assertEqual(code, 2)
        self.assertEqual(self.asked, [], "the model was asked although the dams layer is missing")
        self.assertIn("the dams layer is not there", said)
        self.assertIn("To type it yourself", said)
        self.assertIn("damchain run --set damit --dams", said)
        self.assertIn("--ids DAM_ID", said)

    def test_no_paths_yet_gives_placeholders(self):
        code, said = self.go(["--set", "damit", "run 2801"], {"ids": ["2801"]})
        self.assertEqual(code, 2)
        self.assertEqual(self.asked, [])
        self.assertIn("--dams DAMS.gpkg --out OUT_FOLDER --dem DEM.tif --ids DAM_ID", said)

    def test_a_refusal_of_the_words_ends_with_the_command_and_its_real_paths(self):
        code, said = self.go(["--set", "damit", "--dams", self.dams, "--out", os.path.join(self.tmp, "runs"),
                              "--dem", self.dem, "run 2801 with ANUGA"],
                             {"ids": ["2801"], "cell_m": None, "solver": "", "manning": None, "redo": False,
                              "unsupported": ["ANUGA"]})
        self.assertEqual(code, 2)
        self.assertIn("Not run:", said)
        self.assertIn("To type it yourself", said)
        self.assertIn(self.dams, said)

    def test_ollama_down_is_one_plain_line(self):
        code, said = self.go(["--set", "damit", "--dams", self.dams, "--out", os.path.join(self.tmp, "runs"),
                              "--dem", self.dem, "run 2801"], urllib.error.URLError(ConnectionRefusedError(111, "x")))
        self.assertEqual(code, 2)
        self.assertIn("Heim could not read the request. Ollama is not answering", said)
        self.assertIn("damchain run --set damit", said)


class DamchainNoviceTest(unittest.TestCase):
    """Small items: a wrong path before conda; where the results are, and how to ask about them."""

    def test_a_wrong_path_is_said_before_conda_is_looked_for(self):
        tmp = tempfile.mkdtemp(prefix="dc-novice-")
        self.addCleanup(shutil.rmtree, tmp, True)
        keep = DC.QP

        class NoConda(object):
            def __init__(self, *a, **k):
                raise AssertionError("QP (the conda lookup) was reached before the path errors")
        DC.QP = NoConda
        args = type("A", (), dict(set="damit", dams=os.path.join(tmp, "missing.gpkg"), out=os.path.join(tmp, "o"),
                                  dem=os.path.join(tmp, "missing.tif"), id_field="", ids="2801", ids_csv="",
                                  param=None, runner_param=None, cell=None, solver="", manning=None,
                                  dry_run=False, check_only=False, redo=False, workers=1, threads=1,
                                  dem_units="", anuga=False, lisflood="", lisflood_given=False))()
        out = io.StringIO()
        try:
            with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
                DC.run_damit(args)
        finally:
            DC.QP = keep
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("the dams layer is not there", out.getvalue())
        self.assertIn("the DEM is not there", out.getvalue())

    def test_results_and_the_heim_runs_add_line(self):
        rows = [{"Dam": "2801", "Status": "done", "Folder": "/r/2801"},
                {"Dam": "4031", "Status": "failed", "Folder": "/r/4031"},
                {"Dam": "9999", "Status": "done", "Folder": "/r/9999"}]
        out = io.StringIO()
        with redirect_stdout(out):
            DC.print_results(rows, ["2801", "4031"], "/r out")
        said = out.getvalue()
        self.assertIn("2801", said)
        self.assertIn("/r/4031", said)
        self.assertNotIn("9999", said)                       # not one of the dams asked for
        self.assertIn("heim runs add '/r out'", said)
        out = io.StringIO()
        with redirect_stdout(out):
            DC.print_results([{"Dam": "4031", "Status": "failed", "Folder": "/r/4031"}], ["4031"], "/r")
        self.assertNotIn("heim runs add", out.getvalue())     # nothing finished: nothing to read in


class AiPageRouteTest(unittest.TestCase):
    """Item 4: Pick for me sends a question about the literature to Vor."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ai-route-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        vdir = os.path.join(self.tmp, "vor")
        os.makedirs(vdir)
        open(os.path.join(vdir, "vor.py"), "w").close()
        self.keep = {k: os.environ.get(k) for k in ("VOR_TOOL", "VOR_PYTHON", "HEIM_RUNS_DB")}
        os.environ.update(VOR_TOOL=os.path.join(vdir, "vor.py"), VOR_PYTHON=sys.executable,
                          HEIM_RUNS_DB=os.path.join(self.tmp, "runs.db"))
        self.ui = load("ai_ui_route", os.path.join(TOOLS, "ai_ui.py"))

    def tearDown(self):
        for k, v in self.keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_routes(self):
        for q, who in (("what breach width does Froehlich 2008 give?", "Vor"),
                       ("hazard class for 2 ft at 3 ft/s under TM-11", "Vor"),
                       ("how is the water surface profile computed", "Vor"),
                       ("what does REFINE_NEAR do", "Heim"),
                       ("why does damchain stop at the plugins step", "Heim"),
                       ("what does dam_chain.py do with --ids", "Heim"),
                       ("what does damit_run:batch need", "Heim"),
                       ("why did QGIS crash", "Heim")):
            self.assertEqual(self.ui.route(q)[0], who, q)

    def test_heim_when_vor_is_not_installed(self):
        os.environ["VOR_TOOL"] = os.path.join(self.tmp, "nope", "vor.py")
        self.assertEqual(self.ui.route("what breach width does Froehlich 2008 give?")[0], "Heim")

    def test_the_options_are_plain(self):
        page = source(os.path.join(TOOLS, "ai_ui.py"))
        self.assertIn('<option value="auto">Pick for me</option>', page)
        self.assertIn("Publications (Vor)", page)
        self.assertIn("This software (Heim)", page)


class AiDoctorExtrasTest(unittest.TestCase):
    """Item 8: versions, and whether damchain can reach QGIS here."""

    def setUp(self):
        self.doc = load("ai_doctor_novice", os.path.join(TOOLS, "ai_doctor.py"))

    def test_versions_name_each_tool(self):
        v = self.doc.versions()
        for part in ("heim %s" % re.search(r"rag_query\.py v([\d.]+)", source(os.path.join(TOOLS, "rag_query.py"))).group(1),
                     "heim run %s" % HR.VERSION, "damchain 1.6.1", "heim runs %s" % RR.VERSION):
            self.assertIn(part, v)

    def test_damchain_status_without_conda_or_env(self):
        tmp = tempfile.mkdtemp(prefix="doc-dc-")
        self.addCleanup(shutil.rmtree, tmp, True)
        fake = os.path.join(tmp, "dam_chain.py")
        with open(fake, "w") as fh:
            fh.write("import sys\ndef conda_exe():\n    sys.exit('conda not found')\n")
        self.doc.HERE = tmp
        ready, text = self.doc.damchain_status()
        self.assertFalse(ready)
        self.assertIn("no conda found", text)
        with open(fake, "w") as fh:
            fh.write("import sys\ndef conda_exe():\n    return 'conda'\ndef env_prefix(c, n):\n    sys.exit('no env')\n")
        self.assertIn("no 'ndqgis' environment", self.doc.damchain_status()[1])
        q = os.path.join(tmp, "qgis_process")
        open(q, "w").close()
        with open(fake, "w") as fh:
            fh.write("def conda_exe():\n    return 'conda'\ndef env_prefix(c, n):\n    return %r\n"
                     "def find_qgis_process(p):\n    return %r\n" % (tmp, q))
        ready, text = self.doc.damchain_status()
        self.assertTrue(ready, text)
        self.assertIn("damchain setup", text)

    def test_the_damchain_line_never_changes_the_exit_code(self):
        tmp = tempfile.mkdtemp(prefix="doc-exit-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.doc.HERE = tmp                         # no rag_index.py, no dam_chain.py: nothing installed
        keep = os.environ.get("VOR_TOOL")
        os.environ["VOR_TOOL"] = os.path.join(tmp, "none.py")
        try:
            with redirect_stdout(io.StringIO()) as out:
                code = self.doc.main([])
        finally:
            if keep is None:
                os.environ.pop("VOR_TOOL", None)
            else:
                os.environ["VOR_TOOL"] = keep
        self.assertEqual(code, 0)
        self.assertIn("damchain: not installed", out.getvalue())


class InstallerTextTest(unittest.TestCase):
    """Items 2, 6, 7 and the START-HERE files, by structure (Windows cannot run here)."""

    def test_linux(self):
        t = source(os.path.join(AI, "install-local-ai-linux.sh"))
        self.assertIn('exec > >(tee -a "$INSTALL_LOG") 2>&1', t)
        self.assertIn("trap on_exit EXIT", t)
        self.assertIn("not enough free disk space for the models", t)
        self.assertNotIn('"$OLLAMA" pull "$EMBED" >/dev/null', t)      # the 0.6 GB pull shows its progress
        self.assertIn('"$LOCAL_AI/ai_doctor.py"', t)
        self.assertIn("Try it now", t)
        self.assertIn("For developers", t)
        self.assertIn('"$OFFLINE/Vor/library/."', t)
        self.assertLess(t.index("Try it now"), t.index("For developers"))

    def test_windows(self):
        t = source(os.path.join(AI, "install-local-ai-windows.ps1"))
        for s in ("Start-Transcript -Path $InstallLog -Append", "function Rerun-Note", "trap {",
                  "not enough free disk space for the models", "function Profile-Policy",
                  "Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned", "[switch]$AllowProfileScripts",
                  "*\\WindowsApps\\*", "*>> $CondaLog", "ai_doctor.py", "Try it now", "For developers",
                  "DoNotExpandEnvironmentNames", "-Type ExpandString", "Stop-Log"):
            self.assertIn(s, t, s)
        self.assertNotIn("& $Ollama pull $Embed *> $null", t)
        # a .cmd launcher for every command the profile defines
        functions = set(re.findall(r'\$lines \+= "function ([\w-]+)', t))
        launched = set(re.findall(r"@\('([\w-]+)','[\w.]+\.py'", t)) | {"vor"}
        self.assertTrue(functions, "no profile functions found")
        self.assertEqual(functions - launched, set(), "profile commands without a .cmd launcher")
        self.assertIn("`$env:VOR_PYTHON = '$PyR'", t)
        # the policy question is never asked of a script that cannot answer
        self.assertIn("[Environment]::UserInteractive -and -not [Console]::IsInputRedirected", t)

    def test_windows_braces_and_quotes_balance(self):
        """A rough check for a script nothing here can parse: braces, brackets and parentheses balance
        outside strings and comments, line by line through here-strings."""
        t = source(os.path.join(AI, "install-local-ai-windows.ps1"))
        t = re.sub(r'@"\r?\n.*?\r?\n"@', '""', t, flags=re.S)          # here-strings
        t = re.sub(r"<#.*?#>", "", t, flags=re.S)                      # block comments
        depth = {"{": 0, "(": 0, "[": 0}
        pair = {"}": "{", ")": "(", "]": "["}
        for n, line in enumerate(t.splitlines(), 1):
            i, quote = 0, None
            while i < len(line):
                c = line[i]
                if quote:
                    if c == "`" and quote == '"':
                        i += 2
                        continue
                    if c == quote:
                        if i + 1 < len(line) and line[i + 1] == quote:
                            i += 2
                            continue
                        quote = None
                    elif quote == '"' and c == "$" and line[i + 1:i + 2] == "(":
                        # a subexpression inside a string: skip to its matching parenthesis
                        d, j = 0, i + 1
                        while j < len(line):
                            if line[j] == "(":
                                d += 1
                            elif line[j] == ")":
                                d -= 1
                                if d == 0:
                                    break
                            j += 1
                        i = j
                    i += 1
                    continue
                if c == "#":
                    break
                if c in "'\"":
                    quote = c
                elif c in depth:
                    depth[c] += 1
                elif c in pair:
                    depth[pair[c]] -= 1
                    self.assertGreaterEqual(depth[pair[c]], 0, "line %d closes more than it opened: %s" % (n, line))
                i += 1
            self.assertIsNone(quote, "line %d leaves a string open: %s" % (n, line))
        self.assertEqual(depth, {"{": 0, "(": 0, "[": 0})

    def test_start_here_and_double_click_installers(self):
        for name in ("START-HERE-WINDOWS.txt", "START-HERE-MAC.txt", "START-HERE-LINUX.txt"):
            t = source(os.path.join(AI, name))
            self.assertIn("ai-doctor", t, name)
            self.assertIn('vor "what breach width does Froehlich 2008 give?"', t, name)
        with open(os.path.join(AI, "Install-Windows.cmd"), "rb") as fh:
            cmd = fh.read()
        self.assertIn(b"\r\n", cmd)                                  # cmd.exe reads CRLF batch files safely
        self.assertIn(b"install-local-ai-windows.ps1", cmd)
        self.assertIn(b"pause", cmd)
        mac = os.path.join(AI, "Install-Mac.command")
        self.assertTrue(os.access(mac, os.X_OK), "Finder only runs an executable .command")
        self.assertIn("zsh heim/setup-local-heim.sh && zsh vor/setup-vor.zsh", source(mac))
        readme = source(os.path.join(AI, "README.md"))
        self.assertNotIn("These are Mac tools", readme)
        self.assertIn("START-HERE", readme)


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, o):
        b = json.dumps(o).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/version"):
            return self._json({"version": "0.9.0"})
        if self.path.startswith("/api/tags"):
            return self._json({"models": []})
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(404)
        self.end_headers()


FAKE_OLLAMA = """#!/bin/bash
ST="$FAKE_STATE/models.txt"; touch "$ST"
case "$1" in
  list) echo "NAME ID SIZE MODIFIED"; while read -r m; do echo "$m  abc  1 GB  now"; done < "$ST" ;;
  pull|create) echo "pulling $2 100%"; echo "$2" >> "$ST" ;;
esac
"""
FAKE_CONDA = """#!/bin/bash
E="$FAKE_STATE/envs"; mkdir -p "$E"
if [[ "$1" == env && "$2" == list ]]; then for d in "$E"/*; do [[ -d "$d" ]] && echo "$(basename "$d")  $d"; done; exit 0; fi
if [[ "$1" == create ]]; then n=""; while [[ $# -gt 0 ]]; do [[ "$1" == -n ]] && n="$2"; shift; done
  mkdir -p "$E/$n/bin"; ln -sf "$(command -v python3)" "$E/$n/bin/python"; fi
exit 0
"""
SMALL_DF = """#!/bin/bash
echo "Filesystem 1024-blocks Used Available Capacity Mounted"
echo "/dev/x 100 1 2000000 1% /"
"""


@unittest.skipUnless(os.name == "posix" and shutil.which("bash") and shutil.which("curl") and shutil.which("python3"),
                     "needs bash, curl and python3")
class LinuxInstallerRunTest(unittest.TestCase):
    """The Linux installer run whole against a stand-in Ollama (a local HTTP stub and a fake `ollama`),
    a fake conda and, for the disk check, a fake `df`."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lin-inst-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.httpd = HTTPServer(("127.0.0.1", 0), _Stub)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for name, text in (("ollama", FAKE_OLLAMA), ("conda", FAKE_CONDA)):
            p = os.path.join(self.bin, name)
            with open(p, "w") as fh:
                fh.write(text)
            os.chmod(p, 0o755)
        os.makedirs(os.path.join(self.tmp, "state"))
        # a copy of damit_ai without heim/knowledge (so nothing is indexed) and with an offline Vor library
        self.pkg = os.path.join(self.tmp, "damit_ai")
        shutil.copytree(AI, self.pkg, ignore=shutil.ignore_patterns("offline", "__pycache__", "knowledge", "tests"))
        lib = os.path.join(self.pkg, "offline", "Vor", "library")
        os.makedirs(lib)
        with open(os.path.join(lib, "FEMA-P-946.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4 stand-in")

    def run_installer(self, extra_path=None, *args):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        path = os.pathsep.join(([extra_path] if extra_path else []) + [self.bin, "/usr/bin", "/bin"])
        env = {"HOME": home, "PATH": path, "LANG": "C", "FAKE_STATE": os.path.join(self.tmp, "state"),
               "CONDA_EXE": os.path.join(self.bin, "conda"), "HEIM_NO_AUTOSTART": "1"}
        p = subprocess.run(["bash", os.path.join(self.pkg, "install-local-ai-linux.sh"),
                            "--ollama-port=%d" % self.port, "--no-index"] + list(args),
                           cwd=self.pkg, env=env, capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout + p.stderr, home

    def test_a_full_run_ends_with_the_check_and_the_first_commands(self):
        code, out, home = self.run_installer()
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn("models to download:", out)
        self.assertIn("pulling qwen3-embedding:0.6b", out)
        self.assertIn("Check (ai-doctor)", out)
        self.assertIn("versions: heim", out)
        self.assertIn("Try it now", out)
        self.assertLess(out.index("Try it now"), out.index("For developers"))
        self.assertTrue(os.path.isfile(os.path.join(home, "Vor", "library", "FEMA-P-946.pdf")),
                        "the offline pack's library was not copied in")
        self.assertNotIn("Vor's library is empty", out)
        with open(os.path.join(home, "local-ai", "install.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("install-local-ai-linux.sh --ollama-port", log)
        self.assertIn("Try it now", log)
        self.assertNotIn("The install stopped", out)

    def test_too_little_disk_stops_before_any_download_and_says_how_to_carry_on(self):
        fake = os.path.join(self.tmp, "smalldf")
        os.makedirs(fake)
        with open(os.path.join(fake, "df"), "w") as fh:
            fh.write(SMALL_DF)
        os.chmod(os.path.join(fake, "df"), 0o755)
        code, out, home = self.run_installer(fake)
        self.assertNotEqual(code, 0)
        self.assertIn("not enough free disk space for the models", out)
        self.assertIn("1.9 GB is free", out)
        self.assertIn("The install stopped", out)
        self.assertIn("run the", out)
        self.assertNotIn("pulling", out)
        st = os.path.join(self.tmp, "state", "models.txt")
        if os.path.exists(st):
            with open(st) as fh:
                self.assertEqual(fh.read().strip(), "", "a model was pulled before the disk check stopped it")


if __name__ == "__main__":
    unittest.main()
