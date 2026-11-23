"""vor 1.4.9 (2026-11-23 real-model test): the model is told which passages come from the publication the
question names.

Vor read the right pages (WSP 2339 Table 1 p.10, Pierce et al. p.35) but labelled them only "Arcement (1989)
Guide for Selecting..." and "FEMA (2010) Predicting Peak Outflow...". The model decided they were not "WSP 2339"
or "Pierce, Thornton and Abt" and answered '{"findings": [], "not_covered": []}' in 4 s on 7 of 11 failed
questions; one answer said "WSP 2339 is not referenced in any of the provided passages". No model here:
chat() is replaced and the prompts are read."""
import json
import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import vor  # noqa: E402
import eval_vor  # noqa: E402
from test_named_by_authors import make_db, Q as PIERCE_Q, EQ  # noqa: E402

ROW = "Concrete ....... _ 0.012-0.018 0.011"


def hit(cid, doc_id, page, txt, title, path, authors="", year="", org="", number=""):
    return vor.Hit((cid, doc_id, page, str(page), txt, title, path, authors, year, org, number), 0.5)


def wsp(cid=1, page=10, txt="Table 1. Base values of Manning's n\n" + ROW):
    return hit(cid, 5, page, txt, "Guide for Selecting Manning's Roughness Coefficients for Natural Channels and "
               "Flood Plains", "/lib/usgs-wsp-2339.pdf", "Arcement, G.J., Jr.; Schneider, V.R.", "1989",
               "U.S. Geological Survey", "WSP 2339")


def other(cid=9):
    return hit(cid, 7, 204, "Manning's n for concrete pipe is 0.012.", "Hydraulic Design of Highway Culverts",
               "/lib/hds5.pdf", "", "2012", "FHWA", "HDS-5")


class Labels(unittest.TestCase):
    def test_a_report_number_the_title_leaves_out_is_shown(self):
        lab = wsp().model_label()
        self.assertIn("(WSP 2339)", lab)
        self.assertTrue(lab.startswith(wsp().short()))
        self.assertTrue(lab.endswith(", p.10"))
        self.assertNotIn("question names", lab)

    def test_a_number_already_in_the_title_is_not_repeated(self):
        h = hit(1, 3, 5, "x", "FEMA P-946 Inundation Mapping", "/lib/p946.pdf", number="P-946")
        self.assertNotIn("(P-946)", h.model_label())
        h = hit(1, 3, 5, "x", "Inundation Mapping", "/lib/p946.pdf", number=None)
        self.assertEqual(h.model_label(), h.short() + ", p.5")

    def test_the_named_publication_says_so_in_the_questions_words(self):
        lab = wsp().model_label({5: ["WSP 2339"]})
        self.assertIn("from 'WSP 2339', the publication the question names", lab)
        self.assertNotIn("question names", other().model_label({5: ["WSP 2339"]}))

    def test_the_human_report_keeps_the_short_label(self):
        self.assertNotIn("(WSP 2339)", wsp().short())


class NamedByDoc(unittest.TestCase):
    def test_report_number(self):
        db = sqlite3.connect(":memory:")
        db.executescript(vor.SCHEMA)
        db.executemany("INSERT INTO docs (id, title, path, number, org) VALUES (?,?,?,?,?)",
                       [(5, "Guide for Selecting Manning's Roughness Coefficients", "/lib/usgs-wsp-2339.pdf",
                         "WSP 2339", "USGS"), (6, "Other", "/lib/other.pdf", "", "USBR")])
        q = "In USGS WSP 2339, what base Manning's n range is given for a stable concrete channel?"
        got = vor.named_docs(db, q, by_doc=True)
        self.assertEqual(list(got), vor.named_docs(db, q)[0])
        self.assertEqual(list(got), [5])
        self.assertTrue(any("2339" in w for w in got[5]), got)
        self.assertEqual(vor.named_docs(db, "What is a base n value?", by_doc=True), {})
        db.close()

    def test_authors_and_year(self):
        db = make_db()
        got = vor.named_docs(db, PIERCE_Q, by_doc=True)
        self.assertEqual(list(got), [58])
        self.assertTrue(any("Pierce" in w and "2010" in w for w in got[58]), got)
        db.close()


class Prompts(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._chat = vor.chat

    def tearDown(self):
        vor.chat = self._chat

    def fake(self, reply):
        def chat(messages, schema=None, **kw):
            self.sent.append(messages)
            return reply
        vor.chat = chat

    def test_extract_tells_the_model_which_passages_are_the_named_publication(self):
        self.fake(json.dumps({"findings": [{"source": "S1", "quote": ROW, "claim": "concrete 0.012-0.018",
                                            "kind": "value"}], "not_covered": []}))
        ev = vor.Evidence()
        ev.named = {5: ["WSP 2339"]}
        vor.extract(ev, "In USGS WSP 2339, what base n for concrete?", [wsp(), other()])
        user = self.sent[0][-1]["content"]
        self.assertIn("[S1] Arcement (1989) Guide for Selecting", user)
        self.assertIn("(WSP 2339), p.10 (from 'WSP 2339', the publication the question names)", user)
        self.assertIn("[S2] FHWA (2012) Hydraulic Design of Highway Culverts (HDS-5), p.204\n", user)
        self.assertIn("whole row", user)
        self.assertIn("One publication goes by several names", self.sent[0][0]["content"])
        self.assertEqual(len(ev.findings), 1)

    def test_the_retry_carries_the_same_labels(self):
        replies = ['{"findings": [], "not_covered": []}', '{"findings": [], "not_covered": []}']

        def chat(messages, schema=None, **kw):
            self.sent.append(messages)
            return replies.pop(0)
        vor.chat = chat
        ev = vor.Evidence()
        ev.named = {5: ["WSP 2339"]}
        vor.extract(ev, "q", [wsp()])
        self.assertEqual(len(self.sent), 2)
        for m in self.sent:
            self.assertIn("the publication the question names", m[-1]["content"])

    def test_the_write_up_sees_the_label_too(self):
        self.fake("Concrete is 0.012-0.018 [F1].")
        ev = vor.Evidence()
        ev.named = {5: ["WSP 2339"]}
        ev.add_source(wsp())
        ev.findings = [{"F": 1, "source": 1, "quote": ROW, "claim": "c", "kind": "value", "check": "exact",
                        "numbers": []}]
        import io
        vor.synthesize("In WSP 2339, n for concrete?", ev, "ask", io.StringIO())
        self.assertIn("(WSP 2339), p.10 (from 'WSP 2339', the publication the question names); value)",
                      self.sent[0][-1]["content"])

    def test_the_pipeline_fills_ev_named(self):
        with open(os.path.join(HERE, "..", "vor.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("ev.named = named_docs(db, question, by_doc=True)", src)

    def test_pierce_label(self):
        h = hit(4, 58, 35, EQ, "Predicting Peak Outflow from Breached Embankment Dams",
                "/lib/PredictPeakOutflwBrchEmbkDms2010.pdf", "", "2010", "FEMA", "")
        lab = h.model_label({58: ["Pierce, Thornton and Abt (2010)"]})
        self.assertIn("FEMA (2010) Predicting Peak Outflow", lab)
        self.assertIn("from 'Pierce, Thornton and Abt (2010)', the publication the question names", lab)


class EvalMarks(unittest.TestCase):
    def test_a_curly_apostrophe_matches_a_plain_fact(self):
        import re
        ans = "losses principally limited to the owner’s property [1, p.8]."
        self.assertIsNone(re.search("owner'?s property", ans))
        self.assertIsNotNone(re.search("owner'?s property", eval_vor.plain_marks(ans)))
        self.assertEqual(eval_vor.plain_marks("3–4 years"), "3–4 years")   # en dash: the facts match it
        self.assertEqual(eval_vor.plain_marks(None), "")


if __name__ == "__main__":
    unittest.main()
