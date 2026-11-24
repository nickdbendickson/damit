"""ai_ui.py 1.2.0, the Local AI app: fix buttons, jobs, the library and its catalog, uploads, updates,
the one-time launch code and the one-copy app.

Why this exists: on 2026-11-24 a Mac's Vor index was empty for days (189 files never indexed) and the
fixes, the update, the downloads and the answer test were all Terminal commands. The page now runs
them. These tests use stand-in tools (no model, no Ollama, no browser) and check what the page may
run, that long commands carry on as jobs, and that nothing outside the assistants' folders is touched.
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "tools", "ai_ui.py")

FAKE_VOR = '''import os, sys, time
if sys.argv[1:2] == ["ingest"] and os.environ.get("FAKE_SLOW"):
    print("slow ingest", flush=True)
    time.sleep(30)
print("VOR:", " ".join(sys.argv[1:]), "job=%s" % os.environ.get("AI_UI_JOB", ""))
'''
FAKE_FETCH = '''import sys
print("FETCH:", " ".join(sys.argv[1:]))
sys.exit(1 if "--catalog" in sys.argv and "bad" in sys.argv[-1] else 0)
'''
CATALOG = {"about": "Catalog. Group 'nd' = North Dakota material: the 2021 PMP study. Group 'cases' = dam-failure "
                    "investigations. Group 'bad' = a group whose download fails.",
           "groups": {"nd": [{"id": "nd-pmp", "kind": "pdf", "title": "PMP"},
                             {"id": "nd-cat", "kind": "pdf", "title": "Categories"},
                             {"id": "nd-hand", "kind": "manual", "title": "By hand"}],
                      "cases": [{"id": "delhi", "kind": "pdf", "title": "Delhi"},
                                {"id": "old", "kind": "pdf", "title": "Old", "skip": True}],
                      "bad": [{"id": "b1", "kind": "pdf", "title": "B1"}]}}


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as fh:
        fh.write(text)


class AppTest(unittest.TestCase):
    KEYS = ("VOR_TOOL", "VOR_PYTHON", "VOR_HOME", "VOR_DB", "HEIM_RUNS_DB", "HEIM_REPORTS", "LOCAL_AI_HOME",
            "OLLAMA_URL", "OLLAMA_HOST", "FAKE_SLOW", "AI_UI_PORT", "AI_UI_IDLE_SECONDS")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ai-app-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tools = os.path.join(self.tmp, "tools")
        for name, text in (("rag_query.py", "import sys\nRUN_WORDS = ()\nprint('HEIM', sys.argv[1:])\n"),
                           ("run_results.py", "import sys\nprint('RUNS', sys.argv[1:])\n"),
                           ("rag_index.py", "import sys\nprint('INDEX:', ' '.join(sys.argv[1:]))\n"),
                           ("ai_score.py", "import sys\nprint('SCORE:', ' '.join(sys.argv[1:]))\n"),
                           ("ai_doctor.py", "print('  PROBLEM  the index is empty. Run: vor ingest')\n")):
            write(os.path.join(self.tools, name), text)
        self.vor_dir = os.path.join(self.tmp, "local-ai", "vor")
        write(os.path.join(self.vor_dir, "vor.py"), 'VERSION = "1.4.7"\n' + FAKE_VOR)
        write(os.path.join(self.vor_dir, "fetch_asdso.py"), FAKE_FETCH)
        write(os.path.join(self.vor_dir, "reference_sources.json"), json.dumps(CATALOG))
        self.home = os.path.join(self.tmp, "Vor")
        os.makedirs(os.path.join(self.home, "library"))
        self.old = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)
        os.environ.update({"VOR_TOOL": os.path.join(self.vor_dir, "vor.py"), "VOR_PYTHON": sys.executable,
                           "VOR_HOME": self.home, "HEIM_RUNS_DB": os.path.join(self.tmp, "runs.db"),
                           "LOCAL_AI_HOME": os.path.join(self.tmp, "local-ai"),
                           "HEIM_REPORTS": os.path.join(self.tmp, "local-ai", "reports"),
                           "OLLAMA_URL": "http://127.0.0.1:9"})          # nothing answers there
        self.addCleanup(self.restore)
        spec = importlib.util.spec_from_file_location("ai_ui_app_test", SRC)
        self.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ui)
        self.ui.HERE = self.tools
        self.ui.HOME = self.tmp
        self.ui.Handler.key = "k3y"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.ui.Handler)
        self.ui.Handler.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.stop_jobs)
        self.base = "http://127.0.0.1:%d" % self.ui.Handler.port

    def restore(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def stop_jobs(self):
        for j in list(self.ui.JOBS.values()):
            j.stop()
        end = time.time() + 10
        while self.ui.running_job() and time.time() < end:
            time.sleep(0.05)

    # ------------------------------------------------------------------ helpers
    def req(self, path, body=None, key="k3y", raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data=data, headers=dict(headers or {}))
        if body is not None:
            r.add_header("Content-Type", "application/json")
        if key:
            r.add_header("X-Key", key)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, resp.read().decode(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), e.headers

    def js(self, path, body=None, **kw):
        code, text, _ = self.req(path, body, **kw)
        return code, json.loads(text)

    def job(self, body, wait=20):
        code, d = self.js("/api/job", body)
        self.assertEqual(code, 200, d)
        end, text, pos = time.time() + wait, "", 0
        while True:
            _, j = self.js("/api/job?id=%s&from=%d" % (d["id"], pos))
            text += j["text"]
            pos = j["next"]
            if j["status"] != "running" or time.time() > end:
                return j, text
            time.sleep(0.05)

    def index(self, passages):
        db = sqlite3.connect(os.path.join(self.home, "vor.db"))
        db.executescript("CREATE TABLE docs(id INTEGER PRIMARY KEY, sha1 TEXT, path TEXT, title TEXT, authors TEXT, "
                         "year TEXT, org TEXT, number TEXT, pages INTEGER, notext TEXT, backend TEXT, added TEXT, "
                         "meta_src TEXT); CREATE TABLE chunks(id INTEGER PRIMARY KEY, doc_id INTEGER, txt TEXT);")
        for i in range(passages):
            db.execute("INSERT INTO docs(id, path, title, year, number, pages) VALUES(?,?,?,?,?,?)",
                       (i + 1, os.path.join(self.home, "library", "a%d.pdf" % i), "Doc %d" % i, "2015", "P-%d" % i, 9))
            db.execute("INSERT INTO chunks(doc_id, txt) VALUES(?, 't')", (i + 1,))
        db.commit()
        db.close()

    def library_file(self, name="a.pdf"):
        write(os.path.join(self.home, "library", name), b"%PDF-1.4\n", "wb")

    # ------------------------------------------------------------------ status and the banner
    def test_status_names_the_empty_index_and_a_stopped_ollama_with_their_buttons(self):
        self.library_file()
        self.index(0)                                   # the 2026-11-24 Mac: an index file with nothing in it
        _, s = self.js("/api/status")
        fixes = {p["fix"] for p in s["problems"]}
        self.assertEqual(fixes, {"start-ollama", "vor-ingest"})
        self.assertEqual((s["vor"]["files"], s["vor"]["documents"], s["vor"]["passages"]), (1, 0, 0))
        self.assertEqual(s["vor"]["version"], "1.4.7")

    def test_an_indexed_library_has_no_vor_problem(self):
        self.library_file()
        self.index(2)
        _, s = self.js("/api/status")
        self.assertNotIn("vor-ingest", {p["fix"] for p in s["problems"]})
        _, lib = self.js("/api/library")
        self.assertEqual([d["title"] for d in lib["docs"]], ["Doc 0", "Doc 1"])

    def test_an_empty_library_points_to_the_library_tab(self):
        _, s = self.js("/api/status")
        self.assertIn("goto-library", {p["fix"] for p in s["problems"]})

    # ------------------------------------------------------------------ jobs
    def test_a_fix_runs_as_a_job_and_its_log_is_read_as_it_grows(self):
        j, text = self.job({"action": "vor-ingest"})
        self.assertEqual(j["status"], "done", text)
        self.assertIn("VOR: ingest job=1", text)
        self.assertTrue(j["log"].startswith(os.path.join(self.tmp, "local-ai", "logs", "ui-jobs")))
        for action, want in (("vor-tables", "VOR: tables"), ("vor-ocr", "VOR: ocr job"),
                             ("vor-ocr-all", "VOR: ocr --min-fraction 0"), ("heim-compact", "INDEX: --compact")):
            self.assertIn(want, self.job({"action": action})[1])

    def test_one_job_at_a_time_and_stop(self):
        os.environ["FAKE_SLOW"] = "1"
        code, first = self.js("/api/job", {"action": "vor-ingest"})
        self.assertEqual(code, 200)
        code, busy = self.js("/api/job", {"action": "vor-tables"})
        self.assertEqual(code, 409)
        self.assertEqual(busy["job"]["id"], first["id"])
        _, latest = self.js("/api/jobs")
        self.assertEqual(latest["job"]["id"], first["id"])
        self.js("/api/job/stop", {"id": first["id"]})
        end = time.time() + 10
        while self.ui.running_job() and time.time() < end:
            time.sleep(0.05)
        _, j = self.js("/api/job?id=%s&from=0" % first["id"])
        self.assertEqual(j["status"], "stopped")

    def test_only_known_actions_with_checked_values(self):
        for body in ({"action": "rm -rf"}, {"action": "heim-refresh", "name": "a;b", "path": self.tmp},
                     {"action": "heim-refresh", "name": "docs", "path": "/no/such/folder"},
                     {"action": "fetch", "groups": []}, {"action": "fetch", "groups": ["; rm"]},
                     {"action": "score", "which": "--model x"},
                     {"action": "update", "folder": self.tmp}, {"action": "update", "folder": "/"}):
            code, d = self.js("/api/job", body)
            self.assertEqual(code, 400, body)
            self.assertTrue(d["error"])

    def test_heim_refresh_names_the_collection_and_folder(self):
        _, text = self.job({"action": "heim-refresh", "name": "engine_docs", "path": self.home})
        self.assertIn("INDEX: -c engine_docs %s" % self.home, text)

    def test_score_runs_the_answer_test(self):
        self.assertIn("SCORE: --vor", self.job({"action": "score", "which": "vor"})[1])
        self.assertIn("SCORE: \n", self.job({"action": "score", "which": "both"})[1])

    # ------------------------------------------------------------------ catalog
    def test_catalog_counts_what_is_already_here(self):
        refs = os.path.join(self.home, "library", "references")
        write(os.path.join(refs, "nd", "nd-pmp.pdf"), b"%PDF", "wb")
        write(os.path.join(refs, "nd", "nd-cat.pdf"), b"%PDF", "wb")            # present but not "ok": not counted
        write(os.path.join(refs, "manifest.json"), json.dumps({"files": {"nd-pmp": {"status": "ok"},
                                                                          "nd-cat": {"status": "failed: 404"}}}))
        _, lib = self.js("/api/library")
        g = {x["id"]: x for x in lib["groups"]}
        self.assertEqual((g["nd"]["have"], g["nd"]["total"], g["nd"]["manual"]), (1, 2, 1))
        self.assertEqual((g["cases"]["have"], g["cases"]["total"]), (0, 1))     # the skipped entry is not counted
        self.assertTrue(g["nd"]["about"].startswith("North Dakota material"))

    def test_fetch_downloads_then_indexes_even_when_a_download_fails(self):
        j, text = self.job({"action": "fetch", "groups": ["nd", "cases"]})
        self.assertEqual(j["status"], "done", text)
        self.assertIn("FETCH: --catalog nd,cases", text)
        self.assertLess(text.index("FETCH:"), text.index("VOR: ingest"))
        j, text = self.job({"action": "fetch", "groups": ["bad"]})
        self.assertEqual(j["status"], "failed")
        self.assertIn("VOR: ingest", text, "what did download is still indexed")

    # ------------------------------------------------------------------ uploads
    def upload(self, kind, name, data):
        return self.js("/api/upload?kind=%s&name=%s" % (kind, urllib.request.quote(name)), raw=data,
                       headers={"Content-Type": "application/octet-stream"})

    def test_a_dropped_document_lands_in_the_library_under_a_plain_name(self):
        code, d = self.upload("library", "../../evil.pdf", b"%PDF-1.4 one")
        self.assertEqual(code, 200, d)
        self.assertEqual(d["saved"], os.path.join(self.home, "library", "added", "evil.pdf"))
        code, d = self.upload("library", "evil.pdf", b"%PDF-1.4 two")
        self.assertTrue(d["saved"].endswith("evil (2).pdf"), "a second file of the same name is kept beside it")
        self.assertEqual(self.upload("library", "run.sh", b"echo")[0], 400)
        self.ui.UPLOAD_MAX["library"] = 4
        self.assertEqual(self.upload("library", "big.pdf", b"%PDF-1.4")[0], 413)

    def update_zip(self, entries):
        p = os.path.join(self.tmp, "upd.zip")
        with zipfile.ZipFile(p, "w") as z:
            for name, text in entries.items():
                z.writestr(name, text)
        with open(p, "rb") as fh:
            return fh.read()

    def installer_name(self):
        if sys.platform == "darwin":
            return "damit_ai/Install-Mac.command"
        return "damit_ai/install-local-ai-windows.ps1" if os.name == "nt" else "damit_ai/install-local-ai-linux.sh"

    def test_an_update_is_checked_unpacked_and_its_installer_runs_as_a_job(self):
        data = self.update_zip({self.installer_name(): 'echo "INSTALLED job=$AI_UI_JOB"\n',
                                "damit_ai/vor/vor.py": 'VERSION = "1.4.11"\n',
                                "damit_ai/heim/tools/ai_ui.py": 'VERSION = "1.2.0"\n'})
        code, d = self.upload("update", "dam-local-ai-mac-2026-11-24.zip", data)
        self.assertEqual(code, 200, d)
        self.assertEqual((d["now"]["vor"], d["new"]["vor"]), ("1.4.7", "1.4.11"))
        self.assertTrue(d["folder"].startswith(os.path.join(self.tmp, "local-ai", "updates") + os.sep))
        if os.name != "nt":
            j, text = self.job({"action": "update", "folder": d["folder"]})
            self.assertIn("INSTALLED job=1", text)

    def test_an_update_zip_must_be_ours(self):
        for entries in ({"other/thing.txt": "x"}, {"damit_ai/../../escape.sh": "x", self.installer_name(): "x"},
                        {"damit_ai/README.md": "no installer"}):
            code, d = self.upload("update", "x.zip", self.update_zip(entries))
            self.assertEqual(code, 400, entries)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "local-ai", "escape.sh")))
        self.assertEqual(self.upload("update", "x.zip", b"not a zip")[0], 400)
        self.assertEqual(self.upload("update", "x.exe", b"MZ")[0], 400)

    # ------------------------------------------------------------------ the window's key
    def raw_get(self, path, headers=None):
        """A GET that does not follow redirects: (status, headers)."""
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.ui.Handler.port, timeout=10)
        try:
            c.request("GET", path, headers=dict(headers or {}))
            r = c.getresponse()
            r.read()
            return r.status, r.headers
        finally:
            c.close()

    def test_the_launch_code_works_once_and_leaves_a_cookie(self):
        _, d = self.js("/api/launch-code", {})
        code, h = self.raw_get("/launch?c=" + d["code"])
        self.assertEqual((code, h["Location"]), (303, "/"))
        cookie = h["Set-Cookie"]
        self.assertIn("ai_k=k3y", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertEqual(self.raw_get("/launch?c=" + d["code"])[0], 403, "a code works once")
        self.assertEqual(self.raw_get("/launch?c=made-up")[0], 403)
        code, page, _ = self.req("/", key=None, headers={"Cookie": "ai_k=k3y"})
        self.assertEqual(code, 200)
        self.assertIn("Local AI", page)
        self.assertEqual(self.req("/", key=None, headers={"Cookie": "ai_k=wrong"})[0], 403)
        self.assertEqual(self.req("/api/status", key=None, headers={"Cookie": "ai_k=k3y"})[0], 403,
                         "the API takes the key from the page, never from the cookie alone")

    def test_streamed_output_is_http_1_1_chunked(self):
        """1.1.0 sent chunked output under HTTP/1.0, so a browser showed the chunk lengths ("7", "8f")."""
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.ui.Handler.port, timeout=10)
        try:
            c.request("POST", "/api/run", body=json.dumps({"action": "doctor"}),
                      headers={"X-Key": "k3y", "Content-Type": "application/json"})
            r = c.getresponse()
            self.assertEqual((r.version, r.getheader("Transfer-Encoding")), (11, "chunked"))
            self.assertEqual(r.read().decode().strip(), "PROBLEM  the index is empty. Run: vor ingest")
        finally:
            c.close()

    def test_an_old_code_does_not_work(self):
        code = self.ui.Handler.new_code()
        self.ui.Handler.codes[code] = time.time() - 1
        self.assertFalse(self.ui.Handler.use_code(code))

    # ------------------------------------------------------------------ odds and ends
    def test_a_log_is_never_cut_inside_a_character(self):
        job = self.ui.Job("t", [])
        write(job.log, "é" * 10 + "\n", "w")
        text, nxt = job.read(1)                          # starts inside the first é: that one is lost, no more
        self.assertTrue(text.endswith("é" * 9 + "\n"))
        whole, end = job.read(0)
        self.assertEqual(whole, "é" * 10 + "\n")
        self.assertEqual(job.read(end), ("", end))

    def test_folders_and_ollama(self):
        self.assertEqual(self.js("/api/open", {"which": "/etc"})[0], 400)
        self.ui.ollama_binary = lambda: None
        _, d = self.js("/api/start-ollama", {})
        self.assertFalse(d["ok"])
        self.assertIn("not found", d["text"])

    def test_score_history_is_shown(self):
        write(os.path.join(self.tmp, "local-ai", "reports", "SCORE-HISTORY.md"), "# Scores\n| a | b |\n")
        self.assertIn("| a | b |", self.req("/api/scores")[1])

    def test_the_page_turns_doctor_lines_into_buttons(self):
        page = self.ui.PAGE
        for fix in ("vor-ingest", "vor-tables", "vor-ocr", "vor-ocr-all", "heim-compact", "start-ollama",
                    "heim-refresh"):
            self.assertIn('"%s"' % fix, page)
        self.assertIn("setInterval(()=>fetch(\"/api/ping", page)


class OneCopyTest(unittest.TestCase):
    """`ai --app` (the icon) starts the server in the background once, then reuses it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ai-app-one-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {"LOCAL_AI_HOME": os.path.join(self.tmp, "local-ai"), "AI_UI_PORT": "0",
                    "AI_UI_IDLE_SECONDS": "3", "VOR_HOME": os.path.join(self.tmp, "Vor"),
                    "OLLAMA_URL": "http://127.0.0.1:9"}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.addCleanup(self.restore)
        spec = importlib.util.spec_from_file_location("ai_ui_one_copy", SRC)
        self.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ui)
        self.opened = []
        self.ui.open_window = self.opened.append
        self.addCleanup(self.kill)

    def restore(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def kill(self):
        st = self.ui.read_state()
        if st:
            try:
                os.kill(int(st["pid"]), 15)
            except OSError:
                pass

    @staticmethod
    def running(pid):
        try:
            os.kill(int(pid), 0)
        except OSError:
            return False
        try:                                      # a finished child of this test is a zombie until reaped
            return os.waitpid(int(pid), os.WNOHANG) == (0, 0)
        except ChildProcessError:
            return True

    def test_one_copy_then_it_stops_by_itself(self):
        self.assertEqual(self.ui.app_open(), 0)
        st = self.ui.read_state()
        self.assertTrue(self.ui.alive(st))
        self.assertEqual(oct(os.stat(self.ui.state_file()).st_mode & 0o777), "0o600")
        self.assertEqual(self.ui.app_open(), 0)
        self.assertEqual(self.ui.read_state()["pid"], st["pid"], "the second click reuses the running copy")
        self.assertEqual(len(self.opened), 2)
        for url in self.opened:
            self.assertRegex(url, r"^http://127\.0\.0\.1:%d/launch\?c=[\w-]+$" % st["port"])
            self.assertNotIn(st["key"], url, "the key itself is never on a command line")
        end = time.time() + 20                   # watched by its process, not by pinging it (a ping is a window)
        while self.running(st["pid"]) and time.time() < end:
            time.sleep(0.2)
        self.assertFalse(self.running(st["pid"]), "it stops after its idle time with no window")
        time.sleep(0.3)
        self.assertIsNone(self.ui.read_state(), "and removes its state file")

    def test_a_stale_state_file_starts_a_new_copy(self):
        self.ui.write_state(9, "old-key")           # a copy that was killed: nothing answers on port 9
        self.assertEqual(self.ui.app_open(), 0)
        self.assertNotEqual(self.ui.read_state()["key"], "old-key")


if __name__ == "__main__":
    unittest.main()


class InstallerIconTest(unittest.TestCase):
    """The Local AI icon each installer makes (the Linux one is run for real in test_novice_usability)."""
    AI = os.path.dirname(os.path.dirname(HERE))

    def read(self, *parts):
        with open(os.path.join(self.AI, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_mac_app_bundle(self):
        t = self.read("heim", "setup-local-heim.sh")
        self.assertIn('APP="$HOME/Applications/Local AI.app"', t)
        for key in ("<key>CFBundleExecutable</key><string>local-ai</string>",
                    "<key>CFBundleIconFile</key><string>local-ai</string>", "<key>LSUIElement</key><true/>"):
            self.assertIn(key, t)
        start = 'cat > "$APP/Contents/MacOS/local-ai" << LAUNCH\n'
        launcher = t[t.index(start) + len(start):t.index("\nLAUNCH\n")]
        self.assertTrue(launcher.startswith("#!/bin/zsh\n"), launcher[:40])
        self.assertIn('$PYRUN "\\$HOME/local-ai/ai_ui.py" --app', launcher)
        # the settings line, as the heredoc writes it, reads the exports Heim's and Vor's blocks put in ~/.zshrc
        line = launcher.splitlines()[1].replace("\\$", "$")
        tmp = tempfile.mkdtemp(prefix="mac-launch-")
        self.addCleanup(shutil.rmtree, tmp, True)
        write(os.path.join(tmp, ".zshrc"), 'export PATH="/bad"\nexport OLLAMA_MODELS="$HOME/local-ai/models"\n'
                                           'export VOR_HOME="$HOME/Vor"\nexport VOR_EMBED="qwen3-embedding:0.6b"\n'
                                           'alias vor="x"\nexport ND_REPO="$HOME/nd"\n')
        r = subprocess.run(["bash", "-c", line + '\necho "$VOR_HOME|$VOR_EMBED|$OLLAMA_MODELS|$ND_REPO|$PATH"'],
                           capture_output=True, text=True, env={"HOME": tmp, "PATH": "/usr/bin:/bin"})
        self.assertEqual(r.stdout.strip(), "%s/Vor|qwen3-embedding:0.6b|%s/local-ai/models|%s/nd|/usr/bin:/bin"
                         % (tmp, tmp, tmp), "only the assistants' settings are taken, not PATH")
        with open(os.path.join(self.AI, "heim", "icons", "local-ai.icns"), "rb") as fh:
            self.assertEqual(fh.read(4), b"icns")
        mac = self.read("Install-Mac.command")
        self.assertIn('[[ -z "${AI_UI_JOB:-}" && -d "$HOME/Applications/Local AI.app" ]] && /usr/bin/open', mac)

    def test_windows_shortcut(self):
        t = self.read("install-local-ai-windows.ps1")
        block = t[t.index("# The Local AI icon (ai_ui 1.2.0)"):t.index("Ok 'Local AI icon -> your Start menu and desktop'")]
        self.assertIn("if ($DoHeim -and -not $Prefix) {", block)
        self.assertIn("[Environment]::GetFolderPath('Programs')", block)
        self.assertIn("'Local AI.lnk'", block)
        self.assertIn("System32\\wscript.exe", block)
        self.assertIn('sh.ExpandEnvironmentStrings("\' + (Cmd-Path $aiCmd) + \'") & """ --app", 0, False', block)
        with open(os.path.join(self.AI, "heim", "icons", "local-ai.ico"), "rb") as fh:
            self.assertEqual(fh.read(4), b"\x00\x00\x01\x00")
