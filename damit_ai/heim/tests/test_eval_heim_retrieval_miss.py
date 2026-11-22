"""eval_heim 1.3 (2026-11-22): a source that is indexed but not retrieved is a FAIL, not a SKIP.

The first real-model run reported lisflood-openmp-threads as "source not indexed" while KNOWN-BEHAVIOURS.md
was in the collection: the search had missed it, and the SKIP left it out of the score."""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)


class RetrievalMiss(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="eval-miss-")
        self.db = os.path.join(self.tmp, "knowledge.db")
        db = sqlite3.connect(self.db)
        db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, collection TEXT, path TEXT, idx INT, txt TEXT, vec BLOB)")
        db.execute("INSERT INTO chunks (collection, path, idx, txt) VALUES ('heim_knowledge', "
                   "'/k/KNOWN-BEHAVIOURS.md', 0, 'run dams side by side at 1 thread')")
        db.commit()
        db.close()
        self.qfile = os.path.join(self.tmp, "q.json")
        with open(self.qfile, "w") as f:
            json.dump({"collection": "heim_knowledge", "questions": [
                {"id": "indexed-but-missed", "q": "threads?", "doc": "KNOWN-BEHAVIOURS", "facts": ["thread"]},
                {"id": "not-indexed", "q": "x?", "doc": "NO-SUCH-FILE", "facts": ["x"]}]}, f)
        fake = types.ModuleType("rag_query")
        fake.DB, fake.CHAT_MODEL, fake.BASE = self.db, "heim", "http://127.0.0.1:1"
        fake.retrieve = lambda q, coll, k: [(0.5, "heim_knowledge", "/k/RUN-RECIPES.md", 0, "unrelated")]
        fake.chat_payload = lambda *a, **k: {}
        fake.post = lambda *a, **k: {"message": {"content": "use one thread"}}
        self._saved = sys.modules.get("rag_query")
        sys.modules["rag_query"] = fake
        os.environ["HEIM_REPORTS"] = self.tmp

    def tearDown(self):
        if self._saved is not None:
            sys.modules["rag_query"] = self._saved
        else:
            sys.modules.pop("rag_query", None)
        os.environ.pop("HEIM_REPORTS", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_miss_is_a_fail_and_absent_is_a_skip(self):
        import importlib
        import eval_heim
        importlib.reload(eval_heim)                       # picks up HEIM_REPORTS
        out = io.StringIO()
        old = sys.argv
        sys.argv = ["eval_heim.py", "--questions", self.qfile]
        try:
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit):
                    eval_heim.main()
        finally:
            sys.argv = old
        text = out.getvalue()
        self.assertIn("FAIL indexed-but-missed", text)
        self.assertIn("retrieval missed", text)
        self.assertIn("SKIP not-indexed", text)
        self.assertIn("0/1 passed  (1 skipped", text)


if __name__ == "__main__":
    unittest.main()
