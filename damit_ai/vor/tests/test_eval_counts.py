"""eval_vor 1.7: the summary counts questions where vor 1.4.11 asked about the named publication's passages one at
a time, and a failed question names every file its pattern matches. No model and no library: vor's database is
a temporary one and run_pipeline is replaced."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))


class EvalCounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = os.environ.get("VOR_HOME")
        os.environ["VOR_HOME"] = self.tmp
        import vor
        import eval_vor
        self.vor, self.eval = vor, eval_vor
        self.saved = (vor.HOME, vor.REPORTS, vor.DB_PATH, vor.run_pipeline)
        vor.HOME, vor.REPORTS = self.tmp, os.path.join(self.tmp, "reports")
        vor.DB_PATH = os.path.join(self.tmp, "vor.db")
        db = vor.connect()
        db.execute("INSERT INTO docs (id, title, path) VALUES (1, 'EAP', '/lib/FEMA P-64-2013.pdf')")
        db.execute("INSERT INTO docs (id, title, path) VALUES (2, 'EAP sheet', '/lib/FEMA P-64 sheet.pdf')")
        db.commit()
        db.close()

    def tearDown(self):
        self.vor.HOME, self.vor.REPORTS, self.vor.DB_PATH, self.vor.run_pipeline = self.saved
        if self.env is None:
            os.environ.pop("VOR_HOME", None)
        else:
            os.environ["VOR_HOME"] = self.env

    def run_eval(self):
        qf = os.path.join(self.tmp, "q.json")
        with open(qf, "w") as f:
            json.dump({"questions": [{"id": "p64", "q": "how often?", "doc": "p-?64", "pages": [69],
                                      "facts": ["5 years"]}]}, f)

        def fake(q, mode, depth, k, out=None, save=True, **kw):
            ev = self.vor.Evidence()
            ev.calls = [{"passages": 8}, {"passages": 8, "retry": True}, {"passages": 1, "retry": "named"}]
            return None, "nothing", ev
        self.vor.run_pipeline = fake
        argv, sys.argv = sys.argv, ["eval_vor.py", "--questions", qf]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                self.eval.main()
        finally:
            sys.argv = argv
        return buf.getvalue()

    def test_counts_and_names(self):
        out = self.run_eval()
        self.assertIn("asked about the named publication's passages one at a time, 0 of them", out)
        self.assertIn("FEMA P-64-2013.pdf or FEMA P-64 sheet.pdf", out)
        rep = [f for f in os.listdir(self.vor.REPORTS) if f.endswith(".json")]
        with open(os.path.join(self.vor.REPORTS, rep[0])) as f:
            d = json.load(f)
        self.assertEqual((d["named_one_by_one"], d["named_one_by_one_found"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
