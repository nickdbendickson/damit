"""vor 1.4.1 (2026-11-22 real-model test): a report the question names is read first, and a cited sentence
whose quote says the opposite term is called out.

The run read FEMA 333 for none of its four FEMA 333 questions (other FEMA manuals repeat the definitions and
outranked it), and one answer defined HIGH hazard with the LOW hazard quote, which the quote checker passed."""
import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import vor  # noqa: E402

DOCS = [
    (1, "Federal Guidelines for Dam Safety: Hazard Potential Classification", "/lib/FEMA Federal Guidelines HazPotential 333_04.ocr.pdf", "", "FEMA"),
    (2, "Users Manual: Prioritization of Dams through Risk Categorization", "/lib/fema-users-manual-2008.pdf", "", "FEMA"),
    (3, "Inundation Mapping of Flood Risks", "/lib/FEMA Federal Guidelines InundatnMap P946.pdf", "P-946", "FEMA"),
    (4, "Using HEC-RAS for Dam Break Studies", "/lib/hec-td-39.ocr.pdf", "TD-39", "USACE HEC"),
    (5, "Guide for Selecting Manning's Roughness Coefficients", "/lib/usgs-wsp-2339.pdf", "WSP 2339", "USGS"),
    (6, "Something about 333 cubic feet", "/lib/other.pdf", "", "USBR"),
]


class Named(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(vor.SCHEMA)
        self.db.executemany("INSERT INTO docs (id, title, path, number, org) VALUES (?,?,?,?,?)", DOCS)

    def tearDown(self):
        self.db.close()

    def ids(self, q):
        return vor.named_docs(self.db, q)[0]

    def test_report_numbers_find_their_documents(self):
        self.assertEqual(self.ids("In FEMA 333, what defines a high hazard potential dam?"), [1])
        self.assertEqual(self.ids("What does FEMA P-946 say about the downstream limit?"), [3])
        self.assertEqual(self.ids("Froehlich 2008 constants in HEC TD-39?"), [4])
        self.assertEqual(self.ids("In USGS WSP 2339, what base n for concrete?"), [5])

    def test_a_plain_question_names_nothing(self):
        self.assertEqual(self.ids("What is a high hazard potential dam?"), [])
        self.assertEqual(self.ids("A spillway of 333 cfs"), [])

    def test_merge_puts_named_first_without_repeats(self):
        class H:
            def __init__(self, cid):
                self.cid = cid
        merged = vor.merge_hits([H(1), H(2)], [H(2), H(3), H(4)], 3)
        self.assertEqual([h.cid for h in merged], [1, 2, 3])


class Opposite(unittest.TestCase):
    def ev(self, quote):
        e = vor.Evidence()
        e.findings = [{"F": 1, "source": 1, "quote": quote, "claim": "", "kind": "", "check": "exact", "numbers": []}]
        return e

    LOW = ("Low hazard potential.-Dams assigned the low hazard potential classification are those where failure or "
           "misoperation results in no probable loss of human life and low economic and/or environmental losses.")

    def test_high_with_the_low_quote_is_flagged(self):
        flags = vor.opposite_terms("High hazard potential dams are those where failure results in no probable "
                                   "loss of human life [F1].", self.ev(self.LOW))
        self.assertEqual(len(flags), 1)
        self.assertIn("'high'", flags[0])
        self.assertIn("'low'", flags[0])

    def test_matching_term_is_not_flagged(self):
        self.assertEqual(vor.opposite_terms("Low hazard potential dams have no probable loss of human life [F1].",
                                            self.ev(self.LOW)), [])

    def test_uncited_sentence_is_left_to_the_other_check(self):
        self.assertEqual(vor.opposite_terms("High hazard means loss of life.", self.ev(self.LOW)), [])

    def test_shows_under_checks(self):
        e = self.ev(self.LOW)
        e.term_flags = vor.opposite_terms("High hazard dams lose no life [F1].", e)
        self.assertTrue(any(c.startswith("CHECK a sentence says 'high'") for c in vor.checks_summary(e, [], {1}, 0)))


if __name__ == "__main__":
    unittest.main()
