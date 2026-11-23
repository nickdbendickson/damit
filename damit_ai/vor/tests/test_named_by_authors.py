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
        self.assertIn("sq = strip_naming(q, named_spans + named_docs(db, q, spans=True)[2])", src)
        self.assertIn("first += idx.search(sq, k=each, per_doc=each, keep={d})", src)
        self.assertIn("hits = merge_hits(first[:min(4, k)], hits, k)", src)
        self.assertIn("named_docs(db, question, spans=True)", src)


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


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def tearDown(self):
        self.db.close()

    def add_doc(self, did, authors, year, org, pages):
        self.db.execute("INSERT INTO docs (id, title, path, authors, year, org) VALUES (?,?,?,?,?,?)",
                        (did, "doc %d" % did, "/lib/d%d.pdf" % did, authors, year, org))
        for i, (page, txt) in enumerate(pages):
            self.db.execute("INSERT INTO chunks (id, doc_id, page, label, idx, txt, vec) VALUES (?,?,?,'',0,?,x'')",
                            (did * 100 + i, did, page, txt))

    def ids(self, q):
        return vor.named_docs(self.db, q)[0]


class SecondReview(_DbCase):
    """Cases from the second independent review of 1.4.4."""
    def test_cover_pages_only_when_there_is_no_author_metadata(self):
        self.add_doc(5, "Wahl, T. L.", "2010", "", [(2, "As shown by Pierce, Thornton and Abt (2010), length matters.")])
        self.add_doc(21, "Smith, J.", "2010", "", [(3, "References. Pierce, M. W. et al. 2010. Peak outflow.")])
        self.assertEqual(self.ids(Q), [58])
        self.assertEqual(self.ids("What did Pierce et al. (2010) find about length?"), [58])

    def test_cover_in_capitals(self):
        self.db.execute("UPDATE chunks SET txt = ? WHERE doc_id = 58 AND page <= 2",
                        ("PREPARED BY MICHAEL W. PIERCE ET AL. JUNE 2010",))
        self.assertEqual(self.ids("What did Pierce et al. (2010) find about length?"), [58])

    def test_possessives_and_smart_quotes(self):
        self.assertEqual(self.ids("What is Pierce et al.'s (2010) equation?"), [58])
        self.assertEqual(self.ids("What is Pierce et al.\u2019s (2010) equation?"), [58])
        self.assertEqual(self.ids("What did Froehlich\u2019s (2008) paper recommend?"), [61])

    def test_any_agency_in_capitals_one_or_two_documents_only(self):
        self.add_doc(7, "", "2015", "USSD", [])
        self.assertEqual(self.ids("What does USSD (2015) recommend?"), [7])
        for d in range(80, 89):
            self.add_doc(d, "", "2015", "ASDSO", [])
        self.assertEqual(self.ids("What does ASDSO (2015) say about inspections?"), [])

    def test_a_leading_word_before_a_comma_is_dropped(self):
        self.assertEqual(self.ids("Similarly, Froehlich (2008) recommends what?"), [61])
        self.assertEqual(self.ids("Briefly, Froehlich (2008) found what?"), [61])

    def test_accents_year_lists_and_parenthetical_citations(self):
        self.add_doc(8, "Fröhlich, D.", "2008", "", [])
        self.assertEqual(self.ids("What did Fröhlich (2008) find?"), [8])
        self.assertEqual(self.ids("Compare Froehlich (1995a, 2008) on breach width."), [61])
        self.assertEqual(self.ids("What breach width is recommended (Froehlich, 2008)?"), [61])

    def test_a_citation_that_named_nothing_stays_as_search_words(self):
        self.db.execute("INSERT INTO docs (id, title, path, number, org) VALUES (70, 'Hazard', '/lib/FEMA 333.pdf', '', 'FEMA')")
        q = "Which breach width equation does FEMA 333 take from MacDonald and Langridge-Monopolis (1984)?"
        ids, _, spans = vor.named_docs(self.db, q, spans=True)
        self.assertEqual(ids, [70])
        left = vor.strip_naming(q, spans)
        self.assertIn("MacDonald", left)
        self.assertNotIn("333", left)

    def test_contents_pages_as_the_index_stores_them(self):
        page = ("TABLE OF CONTENTS\n\nList of Figures\n" + TOC + "Figure 13 Residuals ...................... 34\n"
                "\nThe report then presents the data and the equations derived from them in some detail.")
        chunks = vor.chunk_page(page)
        self.assertTrue(chunks and "\n" not in chunks[0])
        self.assertTrue(vor.is_contents(chunks[0]))
        self.assertTrue(vor.is_contents(" ".join(TOC.splitlines())))     # numbered entries, no heading

    def test_a_data_sheet_is_not_a_contents_page(self):
        sheet = ("Table 1. Pertinent data, Spillway section Height of dam above streambed, feet .................. 110 "
                 "Crest width, feet .................. 30 Number of spillway gates .................. 6 "
                 "Gate width, feet .................. 40 Reservoir contents, acre-feet .................. 5000")
        self.assertFalse(vor.is_contents(sheet))


class ThirdReview(_DbCase):
    """Cases from the third independent review of 1.4.4."""

    def test_a_reworded_sub_question_is_stripped_too(self):
        sub = "What R2 value did Pierce et al. (2010) report for the embankment length relationship?"
        ids, _, spans = vor.named_docs(self.db, Q, spans=True)
        spans = spans + vor.named_docs(self.db, sub, spans=True)[2]
        self.assertNotIn("Pierce", vor.strip_naming(sub, spans))
        self.assertNotIn("Pierce", vor.strip_naming("How good was the fit of the Pierce, Thornton, and Abt (2010) curve?",
                                                    vor.named_docs(self.db, "Pierce, Thornton, and Abt (2010)", spans=True)[2]))

    def test_more_citation_forms(self):
        for q in ("Breach width (Froehlich, 2008; Wahl, 2004)?", "What breach width does (Froehlich 2008) give?",
                  "Breach width (e.g., Froehlich, 2008)?", "Compare Froehlich (2008a, b) on breach width.",
                  "Breach width per Froehlich (2008, p. 35)?"):
            self.assertEqual(self.ids(q), [61], q)
        self.assertEqual(self.ids("How good is the fit (Pierce et al. 2010)?"), [58])

    def test_letters_beyond_latin_1(self):
        self.add_doc(9, "\u015eent\u00fcrk, F.", "1994", "", [])
        self.add_doc(10, "Miko\u015b, M.", "2011", "", [])
        self.assertEqual(self.ids("What does \u015eent\u00fcrk (1994) give for spillway aeration?"), [9])
        self.assertEqual(self.ids("What did Miko\u015b (2011) find?"), [10])

    def test_co_authors_are_not_dropped(self):
        self.db.execute("DELETE FROM chunks WHERE doc_id = 58")
        self.add_doc(91, "Abt, S. R.; Johnson, T.", "2010", "", [])
        self.assertEqual(self.ids(Q), [])
        self.add_doc(92, "Hunt, S. L.; Temple, D. M.", "2005", "", [])
        self.assertEqual(self.ids("What erodibility did Hanson, Cook and Hunt (2005) measure?"), [])
        self.assertEqual(self.ids("In Utah, Froehlich (2008) said what?"), [])          # not a sentence opener

    def test_junk_author_metadata_still_reads_the_cover(self):
        for junk in ("Administrator", "FEMA", "mpierce", "Michael Pierce"):
            self.db.execute("UPDATE docs SET authors = ? WHERE id = 58", (junk,))
            self.assertEqual(self.ids(Q), [58], junk)
            self.assertEqual(self.ids("What did Pierce et al. (2010) find about length?"), [58], junk)

    def test_more_contents_layouts(self):
        self.assertTrue(vor.is_contents("1.1 Purpose ................ 1-1 1.2 Scope ................ 1-2 "
                                        "1.3 Background ................ 1-3 1.4 Organization ................ 1-4"))
        self.assertTrue(vor.is_contents("Appendix A Glossary ......... A-1 Appendix B References ......... B-1 "
                                        "Appendix C Data ......... C-1"))
        self.assertTrue(vor.is_contents("Contents Page Introduction ........ 1 Background ........ 2 "
                                        "Test Facility ........ 4 Results ........ 12"))
        self.assertTrue(vor.is_contents("1. Introduction ........ 1 2. Site Description ........ 3 "
                                        "3. Geology ........ 7 4. Embankment Performance ........ 11"))
        self.assertFalse(vor.is_contents("Elevation, feet ........ 1450 Surface area, acres ........ 230 "
                                         "Reservoir contents, acre-feet ........ 5000"))

    def test_long_input_is_quick(self):
        import time
        t = time.time()
        vor.named_docs(self.db, ("Abc, " * 9000) + "x (2010)")       # unbounded look-back: about 10 s here
        vor.named_docs(self.db, ("word " * 9000) + "(2010")
        vor.is_contents(". " * 15000 + "1")
        self.assertLess(time.time() - t, 0.5)


class FourthReview(_DbCase):
    """Cases from the fourth independent review of 1.4.4."""
    def test_agency_and_junk_author_fields_still_read_the_cover(self):
        for junk in ("Federal Emergency Management Agency", "U.S. Department of Homeland Security, FEMA",
                     "US Army Corps of Engineers", "U.S. Bureau of Reclamation", "Colorado State University",
                     "Windows User", "Microsoft Office User", "Valued Customer"):
            self.db.execute("UPDATE docs SET authors = ? WHERE id = 58", (junk,))
            self.assertEqual(self.ids(Q), [58], junk)
            self.assertEqual(self.ids("What did Pierce et al. (2010) find about length?"), [58], junk)
        for person in ("Wahl, T. L.", "Tony L. Wahl", "Wahl T."):
            self.db.execute("UPDATE docs SET authors = ? WHERE id = 58", (person,))
            self.assertEqual(self.ids(Q), [], person)

    def test_a_citation_opening_the_question_keeps_its_first_author(self):
        self.db.execute("DELETE FROM chunks WHERE doc_id = 58")
        self.add_doc(93, "Thornton, C. I.; Abt, S. R.", "2010", "", [])
        self.assertEqual(self.ids("Pierce, Thornton and Abt (2010) found what relationship?"), [])
        self.add_doc(94, "Cook, K. R.; Hunt, S. L.", "2005", "", [])
        self.assertEqual(self.ids("Hanson, Cook and Hunt (2005) measured what coefficient?"), [])
        self.assertEqual(self.ids("Plainly, Froehlich (2008) says what?"), [61])     # one word and one name

    def test_ordinary_words_are_not_part_of_the_citation(self):
        spans = vor.named_docs(self.db, "How do the USBR equation and Froehlich (2008) differ for breach width?",
                               spans=True)[2]
        self.assertEqual(spans, ["Froehlich (2008)"])
        q = "For breach width, side slopes and failure time, Froehlich (2008) recommends what?"
        self.assertIn("failure time", vor.strip_naming(q, vor.named_docs(self.db, q, spans=True)[2]))
        self.assertEqual(self.ids("In Oklahoma, piping and Froehlich (2008) found what?"), [61])

    def test_loose_names_in_the_search_terms_go_too(self):
        spans = vor.named_docs(self.db, Q, spans=True)[2]
        for terms in ("Pierce Thornton Abt 2010", "Pierce et al. 2010"):
            left = vor.strip_naming(Q + " " + terms + " peak breach outflow", spans)
            self.assertNotIn("Pierce", left)
            self.assertNotIn("2010", left)
            self.assertIn("peak breach outflow", left)

    def test_numbered_data_sheets_and_checklists_are_not_contents(self):
        sheet = vor.chunk_page("PERTINENT DATA\n1. Drainage area, square miles .......... 230\n"
                               "2. Height of dam above streambed, feet .......... 110\n3. Crest width, feet .......... 30\n"
                               "4. Crest length, feet .......... 1450\n5. Spillway crest elevation, feet .......... 5420\n"
                               "The data above are taken from the 1962 design report and the 1988 survey.")
        self.assertEqual([vor.is_contents(c) for c in sheet], [False])
        self.assertFalse(vor.is_contents("Item Condition Rating 1. Crest settlement .......... 2 2. Upstream slope "
                                         "erosion .......... 3 3. Seepage at toe .......... 1 4. Spillway concrete .......... 2"))

    def test_every_piece_of_a_long_contents_page(self):
        names = ["Introduction", "Background", "Site Description", "Geology", "Hydrology", "Hydraulics", "Embankment",
                 "Foundation", "Seepage Analysis", "Stability Analysis", "Spillway", "Outlet Works", "Instrumentation",
                 "Inspection History", "Deficiencies", "Alternatives", "Cost Estimates", "Recommendations",
                 "Conclusions", "References", "Glossary", "Acknowledgments", "Appendix Data", "Appendix Photos",
                 "Appendix Calculations", "Appendix Drawings", "Appendix Correspondence", "Appendix Hydrographs",
                 "Appendix Boring Logs", "Appendix Laboratory Tests"]
        page = "Table of Contents\n" + "".join("%s .................... %d\n" % (n, 3 * i + 1) for i, n in enumerate(names))
        chunks = vor.chunk_page(page)
        self.assertGreater(len(chunks), 1)
        self.assertEqual([vor.is_contents(c) for c in chunks], [True] * len(chunks))
        self.assertTrue(vor.is_contents("iii Contents Preface ....... 1 Introduction ....... 2 Methods ....... 5 "
                                        "Results ....... 9"))


class FifthReview(_DbCase):
    """Cases from the fifth independent review of 1.4.4."""
    def test_an_agency_in_the_author_field_is_capped_like_an_organisation(self):
        for d in range(1, 6):
            self.add_doc(100 + d, "FEMA", "2013", "FEMA", [])
        self.assertEqual(self.ids("What does FEMA (2013) say about the inflow design flood?"), [])
        self.db.execute("DELETE FROM docs WHERE id > 102")
        self.assertEqual(self.ids("What does FEMA (2013) say about the inflow design flood?"), [101, 102])

    def test_values_with_commas_or_decimals_are_not_page_numbers(self):
        for page in ("Reservoir storage allocation\nDead storage, acre-feet .......... 1,240\nInactive storage .......... 5,300\n"
                     "Active conservation storage .......... 41,800\nJoint use .......... 62,000\n"
                     "Total capacity .......... 110,340\nMaximum water surface capacity .......... 128,900\n",
                     "Minimum required factors of safety\nEnd of construction .......... 1.3\nSteady seepage .......... 1.5\n"
                     "Surcharge pool .......... 1.4\nRapid drawdown .......... 1.3\nPseudostatic .......... 1.0\n"):
            self.assertEqual([vor.is_contents(c) for c in vor.chunk_page(page + "Values from the 1988 design memorandum.")],
                             [False])

    def test_appendix_pages_follow_high_page_numbers(self):
        self.assertTrue(vor.is_contents("7.3 Results ........ 77 References ........ 79 Appendix A Breach Database "
                                        "........ A-1 Appendix B Photos ........ B-1"))


if __name__ == "__main__":
    unittest.main()
