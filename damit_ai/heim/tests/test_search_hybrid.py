"""Heim's search: vectors as bytes, and exact words fused with meaning (rag_index 2.9, rag_query 2.6).

Why this exists: Heim stored every vector as JSON text (about 2 GB for 124,000 passages, all parsed
again for every question) and searched by meaning alone, so an exact name such as
STABILITY_RETRY_PCT could rank below prose about the same topic. Embeddings are stubbed; no Ollama.
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")


def fake_vec(text):
    """Meaning, as the stub sees it: how much a text talks about retries in prose."""
    t = text.lower()
    return [1.0 + t.count("retry") + t.count("rerun"), 1.0 + t.count("def ") + t.count("_")]


def load(name, db):
    old = os.environ.get("HEIM_DB")
    os.environ["HEIM_DB"] = db
    try:
        spec = importlib.util.spec_from_file_location(name + "_hybrid_test", os.path.join(TOOLS, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if old is None:
            os.environ.pop("HEIM_DB", None)
        else:
            os.environ["HEIM_DB"] = old
    mod.print = lambda *a, **k: None
    return mod


class HybridSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="heim-hybrid-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = os.path.join(self.tmp, "knowledge.db")
        self.rag = load("rag_index", self.db)
        self.rag.embed = lambda texts: [fake_vec(t) for t in texts]
        self.q = load("rag_query", self.db)
        # every question "means" retries in prose, so meaning alone always ranks the prose first
        self.q.post = lambda url, payload, timeout=0: {"embeddings": [[1.0, 0.1] for _ in payload["input"]]}
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src)
        self.write("prose.md", "When a run's volume error is too high the Runner will retry, rerun and retry "
                               "again with a smaller time step. Retry retry rerun.\n")
        self.write("engine.py", "STABILITY_RETRY_PCT = 1.0\n\ndef needs_rerun(err):\n    return err > 1.0\n")
        self.write("other.md", "Manning n of 0.05 is the default roughness.\n")

    def write(self, name, text):
        with open(os.path.join(self.src, name), "w", encoding="utf-8") as f:
            f.write(text)

    def index(self, coll="code"):
        self.rag.index_collection(coll, [self.src])

    def paths(self, question, k=1, coll="all"):
        return [h[2] for h in self.q.Store(coll).search([question], k)]

    def test_vectors_are_stored_as_bytes_and_a_word_index_is_built(self):
        self.index()
        db = sqlite3.connect(self.db)
        try:
            kinds = {r[0] for r in db.execute("SELECT typeof(vec) FROM chunks")}
            self.assertEqual(kinds, {"blob"})
            n = db.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH '\"STABILITY_RETRY_PCT\"'"
                           ).fetchone()[0]
            self.assertEqual(n, 1)
        finally:
            db.close()

    def test_an_exact_name_beats_prose_that_is_closer_in_meaning(self):
        self.index()
        store = self.q.Store("all")
        store.fts = False                      # meaning alone (as before 2.6): the prose wins
        self.assertEqual([h[2] for h in store.search(["what is STABILITY_RETRY_PCT"], 1)], ["prose.md"])
        self.assertEqual(self.paths("what is STABILITY_RETRY_PCT"), ["engine.py"])

    def test_a_reindex_drops_the_old_words(self):
        self.index()
        self.write("engine.py", "LIMIT_PCT = 1.0\n")
        self.index()
        db = sqlite3.connect(self.db)
        try:
            n = db.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH '\"STABILITY_RETRY_PCT\"'"
                           ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(n, 0)
        self.assertEqual(self.paths("LIMIT_PCT"), ["engine.py"])

    def test_words_are_searched_in_the_asked_collection_only(self):
        self.index("code")
        other = os.path.join(self.tmp, "kn")
        os.makedirs(other)
        with open(os.path.join(other, "k.md"), "w") as f:
            f.write("STABILITY_RETRY_PCT is the one percent limit.\n")
        self.rag.index_collection("heim_knowledge", [other])
        self.assertEqual(set(self.paths("STABILITY_RETRY_PCT", k=5, coll="heim_knowledge")), {"k.md"})

    def legacy_db(self):
        """An index as rag_index 2.8 left it: JSON text vectors, no word index."""
        db = sqlite3.connect(self.db)
        db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, collection TEXT NOT NULL, path TEXT NOT NULL, "
                   "idx INTEGER NOT NULL, txt TEXT NOT NULL, vec TEXT NOT NULL)")
        for i, name in enumerate(sorted(os.listdir(self.src))):
            txt = open(os.path.join(self.src, name)).read()
            db.execute("INSERT INTO chunks (collection,path,idx,txt,vec) VALUES (?,?,?,?,?)",
                       ("code", name, 0, txt, json.dumps(fake_vec(txt))))
        db.commit()
        db.close()

    def test_an_old_index_still_answers_and_says_how_to_speed_it_up(self):
        self.legacy_db()
        store = self.q.Store("all")
        self.assertEqual(store.text_vectors, 3)
        self.assertFalse(store.fts)
        self.assertEqual(len(store.search(["roughness"], 3)), 3)
        self.assertIn("WATCH", [l for l, t in self.rag.doctor_checks(ollama=False) if "heim-index --compact" in t])

    def test_compact_converts_in_place_without_embedding(self):
        self.legacy_db()
        self.rag.embed = lambda texts: self.fail("--compact must not re-embed")
        db = self.rag.connect()
        self.rag.ensure_schema(db)
        self.assertEqual(self.rag.compact_vectors(db, vacuum=True), 3)
        db.close()
        store = self.q.Store("all")
        self.assertEqual(store.text_vectors, 0)
        self.assertTrue(store.fts)
        self.assertEqual(self.paths("what is STABILITY_RETRY_PCT"), ["engine.py"])
        self.assertFalse([t for l, t in self.rag.doctor_checks(ollama=False) if "--compact" in t])


if __name__ == "__main__":
    unittest.main()
