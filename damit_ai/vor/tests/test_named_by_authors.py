"""vor 1.4.4 (2026-11-22): a question that names a paper by its authors and year reads that paper first, without
the naming words, and a search no longer spends places on a repeated cover page or a contents page.

The Pierce question ('... did Pierce, Thornton and Abt (2010) find ...') never read p.35, the equation page.
Searched inside that paper p.35 ranked 8th, behind the cover (p.1 and again p.2), two contents pages and pages
citing 'Pierce (2008)'. The report has no author metadata (it is filed under FEMA); its cover names the authors."""
import collections
import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import vor  # noqa: E402

Q = ("What relationship between embankment length and peak breach outflow did Pierce, Thornton and Abt (2010) "
     "find, and how good was the fit?")
COVER = ("PREDICTING PEAK OUTFLOW FROM BREACHED EMBANKMENT DAMS Prepared by M. W. Pierce, C. I. Thornton, "
         "and S. R. Abt June 2010 Final Colorado State University")
TOC = ("Figure 10 Comparison of the MacDonald and Costa best-fit equations ..................... 31\n"
       "Figure 11 Observed and predicted peak discharges .................................. 32\n"
       "Figure 12 Comparison of relationships ............................................. 33\n")
EQ = "Qp = 0.1202 (L)1.7856 Equation 8 The resulting relationship presented in Equation 8 has an R2 value of 0.909."


def make_db():
    db = sqlite3.connect(":memory:")
    db.executescript(vor.SCHEMA)
    docs = [(58, "Predicting Peak Outflow from Breached Embankment Dams", "/lib/PredictPeakOutflwBrchEmbkDms2010.pdf",
             "", "2010", "FEMA"),
            (59, "Another 2010 report", "/lib/other2010.pdf", "", "2010", "USBR"),
            (60, "A 2008 thesis", "/lib/pierce2008.pdf", "Pierce, M. W.", "2008", ""),
            (61, "Froehlich paper", "/lib/froehlich.pdf", "David C. Froehlich", "2008", "")]
    db.executemany("INSERT INTO docs (id, title, path, authors, year, org) VALUES (?,?,?,?,?,?)", docs)
    chunks = [(1, 58, 1, COVER), (2, 58, 2, COVER), (3, 58, 4, TOC), (4, 58, 35, EQ),
              (5, 59, 1, "Annual report 2010. Pierce county roads."), (6, 60, 1, "Pierce thesis")]
    db.executemany("INSERT INTO chunks (id, doc_id, page, label, idx, txt, vec) VALUES (?,?,?,'',0,?,x'')",
                   [(c, d, p, t) for c, d, p, t in chunks])
    return db


class AuthorYear(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def tearDown(self):
        self.db.close()

    def test_authors_on_the_cover_name_the_report(self):
        self.assertEqual(vor.named_docs(self.db, Q)[0], [58])

    def test_year_must_match(self):
        self.assertEqual(vor.named_docs(self.db, Q.replace("(2010)", "(2011)"))[0], [])

    def test_one_surname_needs_the_authors_field(self):
        self.assertEqual(vor.named_docs(self.db, "What did Froehlich (2008) recommend?")[0], [61])
        self.assertEqual(vor.named_docs(self.db, "What did Pierce (2010) find?")[0], [])   # cover alone: not enough

    def test_report_numbers_still_work(self):
        self.db.execute("INSERT INTO docs (id, title, path, number, org) VALUES (70, 'Hazard', '/lib/FEMA 333.pdf', '', 'FEMA')")
        self.assertEqual(vor.named_docs(self.db, "In FEMA 333, what is high hazard?")[0], [70])

    def test_naming_words_are_left_out_inside_the_document(self):
        q = vor.strip_naming(Q)
        self.assertNotIn("Pierce", q)
        self.assertNotIn("2010", q)
        self.assertIn("embankment length", q)
        self.assertNotIn("333", vor.strip_naming("In FEMA 333, what are the criteria for a low hazard dam?"))
        self.assertEqual(vor.strip_naming("FEMA 333?"), "FEMA 333?")      # too little left: unchanged


class SearchSkips(unittest.TestCase):
    def test_repeated_cover_and_contents_pages_give_way(self):
        db = make_db()
        idx = vor.Index.__new__(vor.Index)
        idx.db = db
        order = [(1, 1.0), (2, 0.9), (3, 0.8), (4, 0.7)]      # cover, cover again, contents, equation page
        idx.vector = lambda q, n, keep=None: order
        idx.lexical = lambda q, n, keep=None: order
        pages = [h.page for h in idx.search("q", k=2, per_doc=4, keep={58})]
        self.assertEqual(pages, [1, 35])
        pages = [h.page for h in idx.search("q", k=3, per_doc=4, keep={58})]
        self.assertEqual(pages, [1, 35, 4])                     # contents only when nothing else is left
        db.close()

    def test_is_contents(self):
        self.assertTrue(vor.is_contents(TOC))
        self.assertFalse(vor.is_contents(EQ))
        self.assertFalse(vor.is_contents("The ratio is 1.0... and 2.0. See p. 12."))

    def test_pipeline_uses_the_stripped_question_and_four_passages(self):
        with open(os.path.join(HERE, "..", "vor.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("idx.search(strip_naming(q), k=min(4, k), per_doc=4, keep=set(named))", src)


class ReviewFixes(unittest.TestCase):
    """Cases from the independent review of 1.4.4."""
    def setUp(self):
        self.db = make_db()

    def tearDown(self):
        self.db.close()

    def ids(self, q):
        return vor.named_docs(self.db, q)[0]

    def test_words_that_are_not_names(self):
        self.assertEqual(self.ids("However, Froehlich (2008) says what?"), [61])
        self.assertEqual(self.ids("What did Froehlich's (2008) paper recommend?"), [61])
        self.assertEqual(self.ids("What failed at Oroville Dam (2017)?"), [])

    def test_et_al_reads_the_front_pages(self):
        self.assertEqual(self.ids("What did Pierce et al. (2010) find about length?"), [58])

    def test_an_organisation_and_year(self):
        self.assertEqual(self.ids("What does USBR (2010) say?"), [59])
        self.assertEqual(self.ids("What does NRCS (2010) say?"), [])

    def test_year_stored_as_a_number_or_date(self):
        self.db.execute("UPDATE docs SET year = '2008-05-01' WHERE id = 61")
        self.assertEqual(self.ids("What did Froehlich (2008) recommend?"), [61])
        self.db.execute("UPDATE docs SET year = 2008 WHERE id = 61")
        self.assertEqual(self.ids("What did Froehlich (2008) recommend?"), [61])

    def test_strip_naming_counts_only_real_words(self):
        self.assertEqual(vor.strip_naming("What does FEMA 333 say?"), "What does FEMA 333 say?")

    def test_merge_hits_drops_the_same_text_twice(self):
        H = collections.namedtuple("H", "cid doc_id txt page")
        a, b, c = H(1, 58, COVER, 1), H(2, 58, COVER, 2), H(3, 59, COVER, 1)
        self.assertEqual([h.cid for h in vor.merge_hits([a], [b, c], 5)], [1, 3])   # other doc: kept

    def test_same_words_in_two_documents_or_two_table_pieces_are_kept(self):
        self.assertNotEqual(vor.text_key(58, COVER), vor.text_key(59, COVER))
        self.assertNotEqual(vor.text_key(58, "Table 3 | n | v\n0.05 | 1"), vor.text_key(58, "Table 3 | n | v\n0.06 | 2"))
        self.assertIsNone(vor.text_key(58, "  "))

    def test_is_contents_leaves_prose_and_data(self):
        dots = "Step one .......... 2\nStep two .......... 3\nStep three .......... 4\n"
        self.assertFalse(vor.is_contents(dots))                    # no contents word
        self.assertFalse(vor.is_contents("Table 4 shows 1.2, 3.4 and 5.6 for each figure."))


if __name__ == "__main__":
    unittest.main()
