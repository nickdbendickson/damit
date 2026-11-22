"""Fewer things to remember (2026-11-22): Ollama starts itself, `ai-doctor` checks both assistants,
`heim help` lists the commands people use.

Why this exists: every assistant failed with "connection refused" until `heim-start` had been run in a
tab of its own, there were two doctors with two command shapes, and about 13 commands with no short list.
No model; nothing is started (the start is stubbed).
"""
import contextlib
import importlib.util
import inspect
import io
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
HEIM = os.path.dirname(HERE)
AI = os.path.dirname(HEIM)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RQ = load(os.path.join(HEIM, "tools", "rag_query.py"), "rq_friendly")
RR = load(os.path.join(HEIM, "tools", "run_results.py"), "rr_friendly")
VOR = load(os.path.join(AI, "vor", "vor.py"), "vor_friendly")
DOC = load(os.path.join(HEIM, "tools", "ai_doctor.py"), "doc_friendly")


class OllamaStartTest(unittest.TestCase):
    def test_one_function_in_three_tools(self):
        src = [inspect.getsource(m.ensure_ollama) for m in (RQ, RR, VOR)]
        self.assertEqual(src[0], src[1])
        self.assertEqual(src[0], src[2])

    def test_a_remote_ollama_or_the_off_switch_is_never_started(self):
        for m in (RQ,):
            del m._OLLAMA_CHECKED[:]
            self.assertFalse(m.ensure_ollama("http://192.0.2.1:9", log=lambda *a: None))
            os.environ["HEIM_NO_AUTOSTART"] = "1"
            try:
                self.assertFalse(m.ensure_ollama("http://127.0.0.1:9", log=lambda *a: None))
            finally:
                os.environ.pop("HEIM_NO_AUTOSTART")

    def test_post_starts_ollama_once_on_connection_refused_then_retries(self):
        calls = {"open": 0, "start": 0}
        real_open = RQ.urllib.request.urlopen

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(req, timeout=0):
            calls["open"] += 1
            if calls["start"] == 0:
                raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))
            return Resp(b'{"embeddings": [[1.0]]}')

        def fake_start(base, log=print):
            calls["start"] += 1
            return True
        RQ.urllib.request.urlopen, real_start = fake_open, RQ.ensure_ollama
        RQ.ensure_ollama = fake_start
        try:
            self.assertEqual(RQ.post("http://127.0.0.1:11434/api/embed", {}), {"embeddings": [[1.0]]})
        finally:
            RQ.urllib.request.urlopen, RQ.ensure_ollama = real_open, real_start
        self.assertEqual((calls["open"], calls["start"]), (2, 1))


class HelpTest(unittest.TestCase):
    def test_heim_help_lists_the_everyday_commands(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
            RQ.command_word(["help"])
        for cmd in ('heim "question"', "heim chat", "heim runs add", "compare", "vor ask", "ai-doctor"):
            self.assertIn(cmd, buf.getvalue())

    def test_help_inside_a_question_is_still_a_question(self):
        self.assertIsNone(RQ.command_word(["help", "me", "read", "a", "mass", "file"]))


class AiDoctorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ai-doctor-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def fake_tool(self, name, text, code):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            f.write("import sys\nprint(%r)\nsys.exit(%d)\n" % (text, code))
        return p

    def test_verdicts(self):
        self.assertEqual(DOC.verdict(0, "  ok  index\n\nAll checks passed."), "OK")
        self.assertEqual(DOC.verdict(0, "  WATCH  old pack"), "WATCH")
        self.assertEqual(DOC.verdict(1, "  PROBLEM  no index"), "PROBLEM")

    def test_runs_both_and_sums_up(self):
        os.environ["VOR_TOOL"] = self.fake_tool("vor.py", "  PROBLEM library empty", 1)
        self.addCleanup(os.environ.pop, "VOR_TOOL", None)
        real = DOC.HERE
        DOC.HERE = self.tmp
        self.fake_tool("rag_index.py", "  WATCH  2 files changed", 0)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = DOC.main([])
        finally:
            DOC.HERE = real
        out = buf.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("Heim  WATCH", out)
        self.assertIn("Vor   PROBLEM", out)

    def test_vor_not_installed_is_not_a_problem(self):
        os.environ["VOR_TOOL"] = os.path.join(self.tmp, "nowhere", "vor.py")
        self.addCleanup(os.environ.pop, "VOR_TOOL", None)
        self.assertIsNone(DOC.vor_command())


if __name__ == "__main__":
    unittest.main()
