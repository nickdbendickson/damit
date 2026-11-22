"""ai-score (2026-11-22): both answer tests in one command, with a dated score history.

These check the parts that need no model: reading each test's report, the history file and its
summary, which questions changed, and that a test's 'Report:' line is followed to its .json.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)
import ai_score  # noqa: E402


def heim_report(path, passed_ids, failed_ids, when="2026-11-22T10:00:00"):
    rows = [{"id": i, "result": "pass", "seconds": 30} for i in passed_ids]
    rows += [{"id": i, "result": "fail", "seconds": 30} for i in failed_ids]
    with open(path, "w") as f:
        json.dump({"model": "heim", "passed": len(passed_ids), "scored": len(rows), "skipped": 2,
                   "when": when, "minutes": 1.0, "rows": rows}, f)
    return path


def vor_report(path, statuses, when="2026-11-22T11:00:00"):
    res = [{"id": k, "status": v} for k, v in statuses.items()]
    scored = [v for v in statuses.values() if v != "skip"]
    with open(path, "w") as f:
        json.dump({"model": "vor", "when": when, "passed": scored.count("pass"), "scored": len(scored),
                   "minutes": 3.5, "results": res}, f)
    return path


class Score(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ai-score-")
        self.hist = os.path.join(self.tmp, "score-history.jsonl")
        self.summ = os.path.join(self.tmp, "SCORE-HISTORY.md")
        self._old = (ai_score.HISTORY, ai_score.SUMMARY)
        ai_score.HISTORY, ai_score.SUMMARY = self.hist, self.summ

    def tearDown(self):
        ai_score.HISTORY, ai_score.SUMMARY = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_both_report_shapes(self):
        h = ai_score.entry_from_report(heim_report(os.path.join(self.tmp, "h.json"), ["a", "b"], ["c"]))
        self.assertEqual((h["assistant"], h["passed"], h["scored"], h["skipped"]), ("heim", 2, 3, 2))
        self.assertEqual(h["results"], {"a": "pass", "b": "pass", "c": "fail"})
        v = ai_score.entry_from_report(vor_report(os.path.join(self.tmp, "v.json"),
                                                  {"x": "pass", "y": "fail", "z": "skip"}))
        self.assertEqual((v["assistant"], v["passed"], v["scored"], v["skipped"]), ("vor", 1, 2, 1))
        self.assertNotIn("z", v["results"])          # a skipped question is not a result

    def test_history_and_changes(self):
        r1 = heim_report(os.path.join(self.tmp, "h1.json"), ["a", "b"], ["c"], when="2026-11-20T09:00:00")
        r2 = heim_report(os.path.join(self.tmp, "h2.json"), ["a", "c"], ["b"], when="2026-11-22T09:00:00")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ai_score.main(["--add", r1, r2]), 0)
        rows = ai_score.load_history()
        self.assertEqual(len(rows), 2)
        self.assertEqual(ai_score.changes(rows[0], rows[1]), (["c"], ["b"]))
        text = open(self.summ).read()
        self.assertIn("## Heim, model heim", text)
        self.assertIn("| 2026-11-20 09:00 | 2 / 3 | 67% | first run |", text)
        self.assertIn("| 2026-11-22 09:00 | 2 / 3 | 67% | +0 pts |", text)
        self.assertIn("now passing c; now failing b.", text)

    def test_history_only_runs_nothing(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(ai_score.main(["--history"]), 0)
        self.assertIn("No runs yet", out.getvalue())
        self.assertFalse(os.path.exists(self.hist))

    def test_follows_report_line(self):
        rep = vor_report(os.path.join(self.tmp, "eval_vor_x.json"), {"x": "pass"})
        fake = os.path.join(self.tmp, "fake_eval.py")
        with open(fake, "w") as f:
            f.write("print('scoring...')\nprint('Report: %s.md')\n" % rep[:-5].replace("\\", "/"))
        with redirect_stdout(io.StringIO()):
            code, path = ai_score.run_eval("Vor", [sys.executable, fake])
        self.assertEqual(code, 0)
        self.assertEqual(os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(rep)))

    def test_heim_eval_prints_report_line_and_time(self):
        src = open(os.path.join(TOOLS, "eval_heim.py"), encoding="utf-8").read()
        self.assertRegex(src, r'print\("report: %s\.md" % base\)')
        self.assertIn('"when": datetime.now()', src)
        vsrc = open(os.path.join(HERE, "..", "..", "vor", "eval_vor.py"), encoding="utf-8").read()
        self.assertIn('say("Report: %s.md" % stem)', vsrc)

    def test_installers_carry_ai_score(self):
        root = os.path.join(HERE, "..", "..")
        for rel, needle in (("install-local-ai-linux.sh", "alias ai-score="),
                            ("install-local-ai-windows.ps1", "function ai-score"),
                            (os.path.join("heim", "setup-local-heim.sh"), 'alias ai-score="')):
            self.assertIn(needle, open(os.path.join(root, rel), encoding="utf-8").read(), rel)
        # `heim-index --compact` (the upgrade step) must be a command on Linux and Windows too, not only the Mac
        self.assertIn("alias heim-index=", open(os.path.join(root, "install-local-ai-linux.sh"), encoding="utf-8").read())
        self.assertIn("function heim-index", open(os.path.join(root, "install-local-ai-windows.ps1"), encoding="utf-8").read())
        mac_vor = open(os.path.join(root, "vor", "setup-vor.zsh"), encoding="utf-8").read()
        self.assertIn('cp "$HERE/eval_vor.py" "$TOOL_DIR/eval_vor.py"', mac_vor)


if __name__ == "__main__":
    unittest.main()
