"""ai_ui.py (the `ai` page): routing, streaming, and the guards that keep it to this machine.

Why this exists: both assistants were terminal-only, with about 13 commands to remember. The page runs
the same commands, so these tests use stand-in tools beside a copy of ai_ui.py. No model, no browser.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "tools", "ai_ui.py")

FAKE_RAG = '''import sys
RUN_WORDS = ("depth", "peak")
print("HEIM ANSWER:", " ".join(sys.argv[1:]))
'''
FAKE_RUNS = '''import sys
def dams_named_in(text, db=None):
    return ["DWR-2801"] if "2801" in text else []
def match_runs(db, dam):
    return []
print("RUNS:", " ".join(sys.argv[1:]))
'''
FAKE_VOR = '''import sys
print("VOR:", " ".join(sys.argv[1:]))
print("see file:///lib/FEMA%20P-946.pdf#page=8")
'''


class UiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ai-ui-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, text in (("rag_query.py", FAKE_RAG), ("run_results.py", FAKE_RUNS),
                           ("ai_doctor.py", "print('  ok  all good')\n")):
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write(text)
        vor_dir = os.path.join(self.tmp, "vor")
        os.makedirs(vor_dir)
        with open(os.path.join(vor_dir, "vor.py"), "w") as f:
            f.write(FAKE_VOR)
        self.env = {"VOR_TOOL": os.path.join(vor_dir, "vor.py"), "VOR_PYTHON": sys.executable,
                    "VOR_HOME": os.path.join(self.tmp, "Vor"), "HEIM_RUNS_DB": os.path.join(self.tmp, "runs.db")}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        spec = importlib.util.spec_from_file_location("ai_ui_test", SRC)
        self.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ui)
        self.ui.HERE = self.tmp
        self.ui.Handler.key = "k3y"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.ui.Handler)
        self.ui.Handler.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.ui.Handler.port

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def req(self, path, body=None, key="k3y", host=None):
        r = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Content-Type": "application/json"})
        if key:
            r.add_header("X-Key", key)
        if host:
            r.add_header("Host", host)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, resp.read().decode(), resp.headers.get("X-Answered-By")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), None

    def test_page_needs_the_key(self):
        self.assertEqual(self.req("/", key=None)[0], 403)
        code, body, _ = self.req("/?k=k3y", key=None)
        self.assertEqual(code, 200)
        self.assertIn("Heim and Vor", body)
        self.assertIn('const KEY="k3y"', body)

    def test_a_request_from_another_host_name_is_refused(self):
        self.assertEqual(self.req("/?k=k3y", key=None, host="evil.example:80")[0], 403)

    def test_api_needs_the_key(self):
        self.assertEqual(self.req("/api/ask", {"q": "x"}, key=None)[0], 403)
        self.assertEqual(self.req("/api/ask", {"q": "x"}, key="wrong")[0], 403)

    def test_a_question_goes_to_heim(self):
        code, body, who = self.req("/api/ask", {"q": "what does REFINE_NEAR do"})
        self.assertEqual((code, who), (200, "Heim"))
        self.assertIn("HEIM ANSWER: what does REFINE_NEAR do", body)

    def test_a_result_question_naming_a_read_dam_goes_to_the_run_results(self):
        code, body, who = self.req("/api/ask", {"q": "peak flow for 2801?"})
        self.assertEqual(who, "Run results")
        self.assertIn("RUNS: ask peak flow for 2801?", body)

    def test_library_goes_to_vor(self):
        code, body, who = self.req("/api/ask", {"q": "Froehlich width", "target": "vor"})
        self.assertEqual(who, "Vor")
        self.assertIn("VOR: ask Froehlich width", body)

    def test_runs_actions_and_bad_input(self):
        self.assertIn("RUNS: compare 2801", self.req("/api/run", {"action": "compare", "dam": "2801"})[1])
        self.assertEqual(self.req("/api/run", {"action": "compare"})[0], 400)
        self.assertEqual(self.req("/api/run", {"action": "rm -rf"})[0], 400)
        self.assertEqual(self.req("/api/run", {"action": "add", "path": "/no/such/file"})[0], 400)
        self.assertIn("all good", self.req("/api/run", {"action": "doctor"})[1])

    def test_pdfs_only_from_the_library(self):
        lib = os.path.join(self.tmp, "Vor", "library")
        os.makedirs(lib)
        inside = os.path.join(lib, "a.pdf")
        outside = os.path.join(self.tmp, "b.pdf")
        for p in (inside, outside):
            with open(p, "wb") as f:
                f.write(b"%PDF-1.4\n")
        self.assertEqual(self.req("/pdf?path=" + urllib.request.quote(inside))[0], 200)
        self.assertEqual(self.req("/pdf?path=" + urllib.request.quote(outside))[0], 403)
        self.assertEqual(self.req("/pdf?path=" + urllib.request.quote(os.path.join(lib, "..", "b.pdf")))[0], 403)


if __name__ == "__main__":
    unittest.main()
