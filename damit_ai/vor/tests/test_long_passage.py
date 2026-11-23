"""vor 1.4.2 (2026-11-22, second real-model test): passages are fitted in tokens, a long one is cut rather than
ending the reading, and every model call is recorded.

filter-d15f, filter-band and pierce-length each failed in 1-2 s with "8 passages read, the model drew no
quote" and nothing said why. These run without a model: chat() is replaced."""
import json
import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import vor  # noqa: E402

QUOTE = "D15F shall be no greater than 9 x D85B, but not less than 0.2 mm."


def hit(cid, page, txt):
    return vor.Hit((cid, 1, page, str(page), txt, "Filters for Embankment Dams", "/lib/FilterManual.pdf",
                    "", "2011", "FEMA", ""), 0.5)


class LongFirstPassage(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._chat = vor.chat

        def fake_chat(messages, schema=None, **kw):
            self.sent.append(messages[-1]["content"])
            return json.dumps({"findings": [{"source": "S2", "quote": QUOTE, "claim": "max D15F is 9 x D85B",
                                             "kind": "criterion"}], "not_covered": []})
        vor.chat = fake_chat

    def tearDown(self):
        vor.chat = self._chat

    def test_model_is_asked_and_reads_the_rest(self):
        huge = "| " + " | ".join(["x"] * 40000) + " |"          # a runaway table passage
        ev = vor.Evidence()
        vor.extract(ev, "maximum D15F for category 1", [hit(1, 98, huge), hit(2, 114, "Table 5. " + QUOTE)])
        self.assertEqual(len(self.sent), 1, "the model was never asked")
        self.assertIn("[S2]", self.sent[0])
        self.assertIn("passage cut here", self.sent[0])
        self.assertEqual(len(ev.findings), 1)
        self.assertEqual(len(ev.cut), 1)
        self.assertLess(vor.est_tokens(self.sent[0]), vor.NUM_CTX - 2500)
        self.assertEqual(len(ev.calls), 1)
        self.assertEqual(ev.calls[0]["passages"], 2)

    def test_tables_are_counted_in_tokens_not_characters(self):
        table = "Table: 1\n" + "\n".join("| %d | %d.%d | %d |" % (i, i, i, i * 7) for i in range(2000))
        self.assertGreater(vor.est_tokens(table), len(table) / 2)
        self.assertLess(vor.est_tokens("plain words " * 100), 1200 / 3)
        hits = [hit(i, i, table[:vor.PASSAGE_MAX]) for i in range(1, 9)]
        ev = vor.Evidence()
        vor.extract(ev, "q", hits)
        self.assertLess(vor.est_tokens(self.sent[0]), vor.NUM_CTX - 2500)
        self.assertEqual(len(ev.sources), ev.calls[0]["passages"])   # only passages handed over count as read

    def test_a_passage_cut_twice_is_named_once(self):
        huge = "y " * 20000
        ev = vor.Evidence()
        vor.extract(ev, "sub one", [hit(1, 98, huge)])
        vor.extract(ev, "sub two", [hit(1, 98, huge)])
        self.assertEqual(len(ev.cut), 1)

    def test_an_empty_list_is_asked_once_more_in_reverse(self):
        replies = ['{"findings": [], "not_covered": []}',
                   json.dumps({"findings": [{"source": "S2", "quote": QUOTE, "claim": "c", "kind": "k"}]})]
        sent = []

        def chat2(messages, schema=None, **kw):
            sent.append((messages[-1]["content"], kw.get("temperature")))
            return replies[len(sent) - 1]
        vor.chat = chat2
        ev = vor.Evidence()
        vor.extract(ev, "q", [hit(1, 98, "Other manual text."), hit(2, 114, "Table 5. " + QUOTE)])
        self.assertEqual(len(sent), 2)
        self.assertLess(sent[1][0].index("[S2]"), sent[1][0].index("[S1]"))     # reverse order
        self.assertEqual(sent[1][1], 0.5)
        self.assertEqual(len(ev.findings), 1)
        self.assertTrue(ev.calls[1].get("retry"))

    def test_empty_twice_says_so(self):
        vor.chat = lambda messages, schema=None, **kw: '{"findings": [], "not_covered": []}'
        ev = vor.Evidence()
        vor.extract(ev, "q", [hit(1, 98, "a"), hit(2, 114, "b")])
        self.assertEqual(len(ev.calls), 2)
        self.assertIn("twice", vor.no_findings_answer(ev, None))
        self.assertNotIn("too fast", vor.no_findings_answer(ev, None))

    def test_a_reply_with_findings_is_not_asked_again(self):
        ev = vor.Evidence()
        vor.extract(ev, "q", [hit(1, 1, "alpha"), hit(2, 2, QUOTE)])
        self.assertEqual(len(self.sent), 1)


class TablesStaySmall(unittest.TestCase):
    def test_empty_columns_are_dropped(self):
        md = vor.table_markdown([["Category", "", "", "Criterion", ""], ["1", "", "", "9 x D85B", ""],
                                 ["2", "", "", "0.7 mm", ""]])
        self.assertEqual(md.split("\n")[0], "| Category | Criterion |")

    def test_a_mostly_empty_grid_is_not_a_table(self):
        rows = [[("w%d" % i) if j == i else "" for j in range(10)] for i in range(10)]   # words on a diagonal
        self.assertEqual(vor.table_markdown(rows), "")

    def test_no_table_passage_outgrows_the_limit(self):
        rows = [["h1", "h2"], ["x" * 20000, "y"], ["1", "2"]]
        for c in vor.table_chunks("Table 1. Long", vor.table_markdown(rows)):
            self.assertLessEqual(len(c), vor.PASSAGE_MAX)


class Check(unittest.TestCase):
    def test_long_passages_lists_the_long_ones(self):
        db = sqlite3.connect(":memory:")
        db.executescript(vor.SCHEMA)
        db.execute("INSERT INTO docs (id, title, path) VALUES (1, 't', '/lib/a.pdf')")
        db.execute("INSERT INTO chunks (doc_id, page, label, idx, txt, vec) VALUES (1, 5, '5', 1000, ?, x'')",
                   ("z" * (vor.PASSAGE_MAX + 1),))
        db.execute("INSERT INTO chunks (doc_id, page, label, idx, txt, vec) VALUES (1, 6, '6', 0, 'short', x'')")
        rows = vor.long_passages(db)
        self.assertEqual([(r[0], r[2], r[3]) for r in rows], [(1, 5, vor.PASSAGE_MAX + 1)])
        db.close()

    def test_eval_keeps_the_log_and_the_cuts(self):
        with open(os.path.join(HERE, "..", "eval_vor.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('lg = log.getvalue()', src)
        self.assertIn('r["calls"]', src)
        self.assertIn('r["cut"]', src)


if __name__ == "__main__":
    unittest.main()
