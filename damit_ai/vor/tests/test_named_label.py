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

    def pipeline(self, keep):
        db = make_db()
        page35 = vor.Hit((4, 58, 35, "35", EQ, "Predicting Peak Outflow from Breached Embankment Dams",
                          "/lib/PredictPeakOutflwBrchEmbkDms2010.pdf", "", "2010", "FEMA", ""), 0.5)

        class Idx:
            def search(self, q, k=8, per_doc=3, keep=None):
                return [page35]
        self.fake('{"findings": [], "not_covered": []}')
        import io
        try:
            vor._run_pipeline(db, PIERCE_Q, "ask", 1, 8, io.StringIO(), Idx(), False, keep, None, "")
        finally:
            db.close()
        return self.sent[0][-1]["content"]

    def test_the_pipeline_labels_the_named_paper(self):
        self.assertIn("p.35 (from 'Pierce, Thornton and Abt (2010)', the publication the question names)",
                      self.pipeline(None))

    def test_with_doc_the_kept_paper_is_labelled_too(self):
        self.assertIn("the publication the question names", self.pipeline({58}))

    def test_with_doc_another_paper_is_not_labelled(self):
        self.assertNotIn("the publication the question names", self.pipeline({59}))

    def test_pierce_label(self):
        h = hit(4, 58, 35, EQ, "Predicting Peak Outflow from Breached Embankment Dams",
                "/lib/PredictPeakOutflwBrchEmbkDms2010.pdf", "", "2010", "FEMA", "")
        lab = h.model_label({58: ["Pierce, Thornton and Abt (2010)"]})
        self.assertIn("FEMA (2010) Predicting Peak Outflow", lab)
        self.assertIn("from 'Pierce, Thornton and Abt (2010)', the publication the question names", lab)


class Plainly(unittest.TestCase):
    """The independent review of 1.4.9: loose matches only reorder the reading; they must not be labelled."""
    DOCS = [(1, "Selecting and Accommodating Inflow Design Floods for Dams", "/lib/fema_p-94.pdf", "P-94", "FEMA"),
            (2, "Guidelines for Dam Breach Analysis", "/lib/fema_p-946.pdf", "P-946", "FEMA"),
            (3, "Hydraulic Design of Highway Culverts", "/lib/hds5.pdf", "HDS-5", "FHWA"),
            (4, "Hydraulic Design of Energy Dissipators", "/lib/hds51.pdf", "HDS-51", "FHWA"),
            (5, "Guidelines for Determining Flood Flow Frequency Bulletin 17C", "/lib/b17c.pdf", "Bulletin 17C", "USGS"),
            (6, "Selecting Analytical Tools for Concrete Dams", "/lib/FEMA_P-1025.pdf", "P-1025", "FEMA"),
            (7, "FEMA 2013 guidance A", "/lib/a.pdf", "", "FEMA"), (8, "FEMA 2013 guidance B", "/lib/b.pdf", "", "FEMA"),
            (9, "Federal Guidelines for Dam Safety: Hazard Potential Classification",
             "/lib/FEMA Federal Guidelines HazPotential 333_04.ocr.pdf", "", "FEMA"),
            (10, "Guide for Selecting Manning's Roughness Coefficients", "/lib/usgs-wsp-2339.pdf", "", "USGS"),
            (11, "Engineering and Design: Hydrologic Engineering Requirements", "/lib/EM_1110-2-1417.pdf", "", "USACE")]

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(vor.SCHEMA)
        self.db.executemany("INSERT INTO docs (id, title, path, number, org) VALUES (?,?,?,?,?)", self.DOCS)

    def tearDown(self):
        self.db.close()

    def named(self, q):
        return vor.named_docs(self.db, q, by_doc=True)

    def test_a_shorter_number_does_not_label_the_longer_one(self):
        self.assertEqual(list(self.named("What inflow design flood does FEMA P-94 recommend?")), [1])
        self.assertEqual(list(self.named("What does HDS-5 say about inlet control?")), [3])
        self.assertEqual(list(self.named("What does FEMA P-946 say about the downstream limit?")), [2])

    def test_a_letter_after_the_number_is_another_edition(self):
        self.assertEqual(self.named("What skew does Bulletin 17B use?"), {})

    def test_a_page_and_a_year_are_not_report_numbers(self):
        self.assertNotIn(6, self.named("WSP 2339 Table 1 on p 10: n for concrete?"))
        self.assertEqual(self.named("In FEMA 2013 guidance, what is the hazard classification?"), {})

    def test_plain_names_still_label(self):
        self.assertEqual(list(self.named("In FEMA 333, what defines a high hazard dam?")), [9])
        self.assertEqual(list(self.named("In WSP 2339, what base n for concrete?")), [10])
        self.assertEqual(list(self.named("What does EM 1110-2-1417 require?")), [11])

    def test_reading_order_is_unchanged(self):
        self.assertEqual(vor.named_docs(self.db, "What inflow design flood does FEMA P-94 recommend?")[0], [1, 2])


class PlainlyRound2(unittest.TestCase):
    """The second independent review of 1.4.9."""
    DOCS = [(1, "Engineering and Design: Earthquake Design and Evaluation", "/l/EM_1110-2-1806.pdf", "", "USACE"),
            (2, "Guidelines for Determining Flood Flow Frequency", "/l/Bulletin 17C.pdf", "", "USGS"),
            (3, "Guidelines for Determining Flood Flow Frequency (1976)", "/l/Bulletin 17.pdf", "", "WRC"),
            (4, "Example Application Guide", "/x/fema_p-2006.pdf", "", "FEMA"),
            (5, "Inundation Mapping", "/lib/FEMA Federal Guidelines InundatnMap P946.pdf", "", "FEMA"),
            (6, "Water Supply Paper", "/x/wsp_2006.pdf", "", "USGS")]

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(vor.SCHEMA)
        self.db.executemany("INSERT INTO docs (id, title, path, number, org) VALUES (?,?,?,?,?)", self.DOCS)

    def tearDown(self):
        self.db.close()

    def named(self, q):
        return vor.named_docs(self.db, q, by_doc=True)

    def test_another_series_with_the_same_number(self):
        self.assertEqual(self.named("What does ER 1110-2-1806 require?"), {})
        self.assertEqual(self.named("What does EM 1110-2-1806 require?"), {1: ["EM 1110-2-1806"]})

    def test_the_edition_letter_in_the_question(self):
        self.assertEqual(self.named("What does Bulletin 17C say about skew?"), {2: ["Bulletin 17C"]})
        self.assertEqual(self.named("What does Bulletin 17B say about skew?"), {})
        self.assertEqual(self.named("What did Bulletin 17 say?"), {3: ["Bulletin 17"]})

    def test_a_report_number_that_looks_like_a_year(self):
        self.assertEqual(list(self.named("What does FEMA P-2006 say about retrofit?")), [4])
        self.assertEqual(list(self.named("What does WSP 2006 say?")), [6])

    def test_lower_case_and_spaced_forms(self):
        self.assertEqual(list(self.named("what does fema p-946 say about inundation?")), [5])
        self.assertEqual(list(self.named("what does FEMA P 946 say about inundation?")), [5])


class Checks(unittest.TestCase):
    PAGE = "Table 1\nConcrete ....... _ 0.012-0.018 0.011\nRock cut ....... .025\nSand ....... .3 .017"

    def test_a_row_without_its_dot_leaders_checks(self):
        for q in ("Concrete 0.012-0.018 0.011", "Concrete ....... _ 0.012-0.018 0.011", "Rock cut .025",
                  "Sand .3 .017"):
            self.assertEqual(vor.quote_check(q, self.PAGE), "exact", q)

    def test_leaders_touching_the_number(self):
        page = "Concrete, trowel finish.........0.013 for lined channels"
        self.assertEqual(vor.quote_check("Concrete, trowel finish 0.013 for lined channels", page), "exact")
        self.assertEqual(vor.quote_check("Concrete, trowel finish 0.015 for lined channels", page), "numbers differ")

    def test_numbers_after_letters_and_inside_a_longer_number(self):
        page = "ranges 1.0...2.0 for the Q100 peak and D_15 filters; roughness was 0.015 at the reach"
        self.assertEqual(vor.quote_check("ranges 1.0...2.5 for the Q100 peak", page), "numbers differ")
        self.assertEqual(vor.quote_check("ranges 1.0...2.0 for the Q500 peak", page), "numbers differ")
        self.assertNotEqual(vor.quote_check("roughness was 0.01 at the reach", page), "exact")
        self.assertEqual(vor.numbers_outside("the Q500 peak", "the Q100 peak", page), ["500"])

    def test_a_changed_number_without_a_leading_zero_is_caught(self):
        self.assertEqual(vor.quote_check("Sand .3 .018", self.PAGE), "numbers differ")
        self.assertEqual(vor.quote_check("Concrete 0.012-0.019 0.011", self.PAGE), "numbers differ")
        self.assertEqual(vor.nums("n .017 and 0.017, 1,240"), ["0.017", "0.017", "1,240"])
        self.assertEqual(vor.numbers_outside("n is 0.017", "Sand .3 .017", self.PAGE), [])
        self.assertEqual(vor.numbers_outside("n is 0.019", "Sand .3 .017", self.PAGE), ["0.019"])

    def test_the_source_label_wins_over_a_report_number(self):
        sent = []
        real = vor.chat

        def chat(messages, schema=None, **kw):
            sent.append(1)
            return json.dumps({"findings": [{"source": "WSP 2339 (S1)", "quote": ROW, "claim": "c", "kind": "value"}],
                               "not_covered": []})
        vor.chat = chat
        try:
            ev = vor.Evidence()
            vor.extract(ev, "q", [wsp()])
        finally:
            vor.chat = real
        self.assertEqual(len(ev.findings), 1, ev.rejected)


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
