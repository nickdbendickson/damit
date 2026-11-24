"""vor 1.4.11 (2026-11-23 real-model test, 21/24): two questions got '{"findings": [], "not_covered": []}' in about
5 s, twice, with the answer page among the passages and labelled as the publication the question names
(wsp2339-floodplain-veg-very-large, WSP 2339 p.15; pierce-length, Pierce et al. p.35). A third try now hands the
named publication's passages to the model one at a time. And a claim that repeats the question's 'WSP 2339' is no
longer flagged as holding a number that is not on its page. No model here: chat() is replaced."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import vor  # noqa: E402

EMPTY = '{"findings": [], "not_covered": []}'
ROW = "| Very large | 0.050-0.100 | Flood-plain vegetation over half the flow depth |"


def hit(cid, doc_id, page, txt, title="Guide for Selecting Manning's Roughness Coefficients",
        path="/lib/usgs-wsp-2339.pdf", number="WSP 2339"):
    return vor.Hit((cid, doc_id, page, str(page), txt, title, path, "Arcement", "1989", "USGS", number), 0.5)


def other(cid, page=4):
    return hit(cid, 7, page, "Summary of state guidelines, page %d." % page, "Summary of Existing Guidelines",
               "/lib/p919.pdf", "P-919")


class OneByOne(unittest.TestCase):
    def setUp(self):
        self._chat = vor.chat
        self.sent = []

    def tearDown(self):
        vor.chat = self._chat

    def fake(self, replies):
        def chat(messages, schema=None, **kw):
            self.sent.append(messages[-1]["content"])
            r = replies[len(self.sent) - 1] if len(self.sent) <= len(replies) else EMPTY
            return r
        vor.chat = chat

    def ev(self, named=True):
        ev = vor.Evidence()
        ev.question = "In WSP 2339, what n adjustment does Table 3 give for a very large amount of vegetation?"
        if named:
            ev.named = {5: ["WSP 2339"]}
        return ev

    def test_named_passages_are_asked_one_at_a_time_after_two_empty_replies(self):
        good = json.dumps({"findings": [{"source": "S1", "quote": ROW, "claim": "WSP 2339 Table 3 gives 0.050 "
                                         "to 0.100 for very large vegetation", "kind": "value"}],
                           "not_covered": []})
        self.fake([EMPTY, EMPTY, EMPTY, good])
        ev = self.ev()
        hits = [hit(1, 5, 14, "Flood-plain adjustments are described on the next page."), other(2),
                hit(3, 5, 15, "Table 3. Adjustment values for flood-plain roughness\n" + ROW), other(4, 9)]
        vor.extract(ev, ev.question, hits)
        self.assertEqual(len(self.sent), 4)                  # first, reversed, then the 2 named passages alone
        one, two = self.sent[2], self.sent[3]
        self.assertIn("[S1]", one)
        self.assertNotIn("[S2]", one)
        self.assertNotIn("[S3]", one)
        self.assertIn("[S3]", two)
        self.assertNotIn("[S1]", two)
        self.assertNotIn("[S4]", two)
        self.assertIn("the publication the question names", two)
        self.assertEqual([c.get("retry") for c in ev.calls], [None, True, "named", "named"])
        self.assertEqual([c["passages"] for c in ev.calls], [4, 4, 1, 1])
        # the model wrote S1 for the only passage it had (S3): the finding is S3's, checked against S3's page
        self.assertEqual(len(ev.findings), 1)
        self.assertEqual(ev.findings[0]["source"], 3)
        self.assertEqual(ev.findings[0]["check"], "exact")
        self.assertEqual(ev.findings[0]["numbers"], [], "2339 and Table 3 come from the question")

    def test_a_quote_not_on_its_page_is_still_rejected(self):
        bad = json.dumps({"findings": [{"source": "S1", "quote": "| Very large | 0.070-0.200 | made up row here |",
                                        "claim": "c", "kind": "value"}], "not_covered": []})
        self.fake([EMPTY, EMPTY, bad])
        ev = self.ev()
        vor.extract(ev, "q", [hit(1, 5, 15, "Table 3.\n" + ROW)])
        self.assertEqual(ev.findings, [])
        self.assertEqual(len(ev.rejected), 1)

    def test_no_named_publication_no_third_try(self):
        self.fake([EMPTY, EMPTY])
        ev = self.ev(named=False)
        vor.extract(ev, "q", [hit(1, 5, 15, "Table 3.\n" + ROW), other(2)])
        self.assertEqual(len(self.sent), 2)

    def test_only_the_named_publications_passages_and_at_most_four(self):
        self.fake([])
        ev = self.ev()
        hits = [hit(i, 5, 10 + i, "page %d of WSP 2339" % i) for i in range(1, 7)] + [other(7)]
        vor.extract(ev, "q", hits)
        self.assertEqual(len(self.sent), 2 + vor.NAMED_ONE_BY_ONE)
        self.assertIn("[S1]", self.sent[2])
        self.assertIn("[S4]", self.sent[-1])
        answer = vor.no_findings_answer(ev, None)
        self.assertIn("twice", answer)
        self.assertIn("4 passage(s) asked about one at a time", answer)

    def test_a_first_reply_with_findings_asks_nothing_more(self):
        good = json.dumps({"findings": [{"source": "S1", "quote": ROW, "claim": "c", "kind": "value"}]})
        self.fake([good])
        ev = self.ev()
        vor.extract(ev, "q", [hit(1, 5, 15, "Table 3.\n" + ROW)])
        self.assertEqual(len(self.sent), 1)

    def test_a_second_reply_with_findings_asks_nothing_more(self):
        good = json.dumps({"findings": [{"source": "S1", "quote": ROW, "claim": "c", "kind": "value"}]})
        self.fake([EMPTY, good])
        ev = self.ev()
        vor.extract(ev, "q", [hit(1, 5, 15, "Table 3.\n" + ROW)])
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(len(ev.findings), 1)


class NumbersFromTheQuestion(unittest.TestCase):
    H = hit(1, 5, 15, "x")

    def check(self, claim, question, quote="| Very large | 0.050-0.100 |", page="Very large 0.050-0.100"):
        return vor.numbers_outside(claim, quote, page, vor._naming_text(question, self.H))

    def test_the_report_number_the_question_says_is_not_flagged(self):
        self.assertEqual(self.check("WSP 2339 gives 0.050 to 0.100.", "What does WSP 2339 give?"), [])

    def test_the_documents_own_number_and_year_are_not_flagged(self):
        self.assertEqual(self.check("Arcement and Schneider (1989), WSP 2339, give 0.050.", "What n?"), [])

    def test_a_table_number_the_question_says_is_not_flagged(self):
        self.assertEqual(self.check("Table 3 gives 0.050.", "What does Table 3 of the guide give?"), [])

    def test_a_value_the_question_says_must_still_be_on_the_page(self):
        self.assertEqual(self.check("The adjustment is 0.070.", "Is the adjustment 0.070 in WSP 2339?"), ["0.070"])

    def test_an_invented_number_is_still_flagged(self):
        self.assertEqual(self.check("WSP 2339 gives 0.050 to 0.150.", "What does WSP 2339 give?"), ["0.150"])

    def test_extract_passes_the_question(self):
        vor_chat = vor.chat
        try:
            vor.chat = lambda m, schema=None, **kw: json.dumps({"findings": [
                {"source": "S1", "quote": ROW, "claim": "WSP 2339 (1989) Table 3: 0.050-0.100", "kind": "value"}]})
            ev = vor.Evidence()
            ev.question = "In WSP 2339, what does Table 3 give for very large vegetation?"
            vor.extract(ev, "sub", [hit(1, 5, 15, "Table 3.\n" + ROW, number="")])
            self.assertEqual(ev.findings[0]["numbers"], [])
        finally:
            vor.chat = vor_chat


if __name__ == "__main__":
    unittest.main()
