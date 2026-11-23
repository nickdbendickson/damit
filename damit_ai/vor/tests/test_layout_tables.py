"""vor 1.4.10: a table printed without ruling lines is read row by row from where its words sit.

Why this exists: on 2026-11-23 four WSP 2339 questions failed with the right page in front of the model.
Tables 1-3 of WSP 2339 have no ruling lines, so PyMuPDF's table finder sees none, and the page's plain text
comes out a column at a time: "Concrete ... Rock cut ... Cobble ... Boulder" then "1-2 2-64 64-256 >256" then
"0.012-0.018 ... 0.030-0.050 0.040-0.070". The model answered that cobble is "2-64 mm" and that Table 3 gives
no value for "Very large" vegetation. These tests use the word boxes of the real pages (USGS WSP 2339, public
domain; read with poppler, the same boxes PyMuPDF's get_text("words") gives) and need no PyMuPDF.
"""
import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "vor.py")
with open(os.path.join(HERE, "data", "wsp2339_words.json"), encoding="utf-8") as _f:
    PAGES = json.load(_f)


def load(home):
    old = {k: os.environ.get(k) for k in ("VOR_HOME", "VOR_DB")}
    os.environ["VOR_HOME"] = home
    os.environ["VOR_DB"] = os.path.join(home, "vor.db")
    try:
        spec = importlib.util.spec_from_file_location("vor_layout_under_test", SRC)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    mod.embed = lambda texts, model=None: [[1.0, 0.0] for _ in texts]
    mod.say = lambda msg: None
    return mod


def words(page):
    return [tuple(w) for w in PAGES[str(page)]["words"]]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="vor-layout-")
        cls.vor = load(cls.home)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def chunks(self, page):
        return self.vor.layout_table_chunks(words(page), PAGES[str(page)]["width"])

    def rows(self, page):
        return [ln for c in self.chunks(page) for ln in c.split("\n")[1:]]


class Table1Test(Base):
    """Table 1 sits in the left column of a two-column page."""

    def test_each_material_keeps_its_size_and_n_range_on_one_line(self):
        rows = self.rows(10)
        self.assertIn("Cobble......... ........ | 64-256 | 0.030-0.050", rows)
        self.assertIn("Concrete ....... | _ | 0.012-0.018 | 0.011", rows)
        self.assertIn("Coarse sand .... ........ | 1-2 | 0.026-0.035", rows)
        self.assertIn("Sand3 .......... ........ | 0.2 | 0.012", rows)
        self.assertIn("Boulder ........ ........ | >256 | 0.040-0.070", rows)

    def test_one_passage_with_the_caption_and_no_running_text_from_either_column(self):
        cs = self.chunks(10)
        self.assertEqual(len(cs), 1)
        self.assertTrue(cs[0].startswith("Table (rows as printed): Table 1. Base values of Manning's n "
                                         "[Modified from Aldridge and Garrett"), cs[0][:120])
        self.assertNotIn("specific weight of water", cs[0], "the right-hand column's text is not in the table")
        self.assertNotIn("moves easily", cs[0], "reading stops at the running text below the table")
        self.assertIn("1 Benson and Dalrymple (1967).", cs[0], "the table's footnotes stay with it")

    def test_the_quote_of_a_row_checks_against_the_passage(self):
        c = self.chunks(10)[0]
        self.assertEqual(self.vor.quote_check("Cobble......... ........ 64-256 0.030-0.050", c), "exact")
        self.assertEqual(self.vor.quote_check("Cobble | 64-256 | 0.030-0.050", c), "exact")
        self.assertEqual(self.vor.quote_check("Concrete 0.012-0.018", c), "exact")


class Table3Test(Base):
    """Table 3 runs the full width; its Example column is running text inside the table."""

    def test_vegetation_and_meander_rows(self):
        rows = self.rows(15)
        self.assertTrue(any(r.startswith("Very large | 0.050-0.100 | Turf grass growing") for r in rows), rows)
        self.assertTrue(any(r.startswith("Extreme | 0.100-0.200 | Dense bushy willow") for r in rows), rows)
        self.assertIn("1.0 | Not applicable.", rows)
        self.assertTrue(any(r.startswith("Degree of") for r in rows))
        self.assertTrue(any(r.startswith("meander") for r in rows))

    def test_every_piece_carries_the_caption_and_fits_a_passage(self):
        cs = self.chunks(15)
        self.assertGreaterEqual(len(cs), 2)
        for c in cs:
            self.assertTrue(c.startswith("Table (rows as printed): Table 3. Adjustment values"), c[:80])
            self.assertLessEqual(len(c), self.vor.CHUNK_MAX + 300)
        self.assertNotIn("Vegetation-Density Method", "\n".join(cs), "reading stops below the table")


class CaptionTest(Base):
    def test_table_1_named_inside_a_cell_does_not_start_a_new_table(self):
        rows = self.rows(41)
        self.assertTrue(any("Table 1 gives an nb value for firm soil of 0.020-0.032. Use 0.025." in r
                            and r.startswith("7 |") for r in rows), rows)
        for c in self.chunks(41):
            self.assertTrue(c.startswith("Table (rows as printed): Table 4. Outline"), c[:80])

    def test_no_caption_no_passage(self):
        ws = [w for w in words(10) if w[4] not in ("Table",)]
        self.assertEqual(self.vor.layout_table_chunks(ws, PAGES["10"]["width"]), [])
        self.assertEqual(self.vor.layout_table_chunks([], 612), [])

    def test_a_caption_over_running_text_is_not_a_table(self):
        w = 612.0
        ws, y = [], 100.0
        for line in ["Table 5. Results of the survey",
                     "The survey covered all of the dams in the state and found that most of them were small",
                     "and that the owners had not inspected them for many years before the program began"]:
            x = 72.0
            for k, t in enumerate(line.split()):
                ws.append((x, y, x + 6.0 * len(t), y + 10.0, t, 0, int(y), k))
                x += 6.0 * len(t) + 3.0
            y += 12.0
        self.assertEqual(self.vor.layout_table_chunks(ws, w), [])


class Synthetic:
    """A page of words set in 10 pt type, 5 pt to a character, for layouts the WSP pages do not have."""

    def __init__(self, width=612.0):
        self.width, self.words, self.block = width, [], 0

    def put(self, x, y, text, skew=0.0):
        self.block += 1
        for k, t in enumerate(text.split()):
            dy = x * skew
            self.words.append((x, y + dy, x + 5.0 * len(t), y + dy + 10.0, t, self.block, 0, k))
            x += 5.0 * len(t) + 2.5
        return self

    def row(self, y, cells, skew=0.0):
        for x, t in cells:
            self.put(x, y, t, skew)
        return self

    def prose(self, x, y, n, width=220):
        words = ("the flow over the plain was measured at each of the sections and the values were then "
                 "compared with those found in other studies of similar streams across the region").split()
        k = 0
        for i in range(n):
            line, w = [], 0
            while w < width:
                line.append(words[k % len(words)])
                w += 5.0 * len(line[-1]) + 2.5
                k += 1
            self.put(x, y + 12 * i, " ".join(line))
        return self

    def tables(self):
        return [c.split("\n") for c in self.vor.layout_table_chunks(self.words, self.width)]


ROWS = [("Sand", "0.2", "0.012"), ("Gravel", "2-64", "0.028"), ("Cobble", "64-256", "0.030"),
        ("Boulder", ">256", "0.040")]


class LayoutCasesTest(Base):
    """The cases the independent review of 1.4.10 built, each of which lost rows or columns before the fix."""

    def page(self, width=612.0):
        p = Synthetic(width)
        p.vor = self.vor
        return p

    def test_a_long_lower_case_first_cell_with_values_beside_it_is_a_row(self):
        p = self.page().put(72, 72, "Table 5. Roughness coefficients for natural channels")
        p.row(88, [(72, "Type of channel"), (380, "Minimum"), (450, "Normal"), (520, "Maximum")])
        data = [("Clean, straight", "0.025"), ("Same, more stones", "0.030"),
                ("Sluggish reaches, weedy, deep pools and backwater", "0.050"), ("Very weedy reaches", "0.075")]
        for i, (a, v) in enumerate(data):
            p.row(100 + 12 * i, [(72, a), (380, v), (450, v), (520, v)])
        rows = [r for t in p.tables() for r in t]
        self.assertIn("Sluggish reaches, weedy, deep pools and backwater | 0.050 | 0.050 | 0.050", rows)
        self.assertIn("Very weedy reaches | 0.075 | 0.075 | 0.075", rows)

    def test_a_full_width_table_under_a_short_caption_on_a_two_column_page_keeps_every_column(self):
        p = self.page().prose(54, 40, 6).prose(320, 40, 6)
        p.put(54, 120, "Table 2. Measured discharges")
        p.row(136, [(54, "Station"), (160, "Date"), (250, "Depth"), (360, "Velocity"), (480, "Discharge")])
        for i in range(4):
            p.row(148 + 12 * i, [(54, "Site %d" % (i + 1)), (160, "198%d" % i), (250, "2.%d" % i),
                                 (360, "3.%d" % i), (480, "1,2%d0" % i)])
        p.prose(54, 220, 6).prose(320, 220, 6)
        t = p.tables()
        self.assertEqual(len(t), 1)
        self.assertIn("Station | Date | Depth | Velocity | Discharge", t[0])
        self.assertIn("Site 1 | 1980 | 2.0 | 3.0 | 1,200", t[0])

    def test_a_left_column_table_beside_running_text_keeps_only_its_column(self):
        p = self.page().prose(54, 40, 4).prose(320, 40, 4)
        p.put(54, 100, "Table 2. Measured depths")
        p.prose(320, 100, 8)
        p.row(116, [(54, "Station"), (160, "Date"), (250, "Depth")])
        for i in range(4):
            p.row(128 + 12 * i, [(54, "Site %d" % (i + 1)), (160, "198%d" % i), (250, "2.%d" % i)])
        t = p.tables()
        self.assertEqual(len(t), 1)
        self.assertIn("Site 1 | 1980 | 2.0", t[0])
        self.assertNotIn("the flow", "\n".join(t[0]))

    def test_a_caption_that_wraps_keeps_its_table(self):
        p = self.page().put(72, 72, "Table 1. Base values of the roughness coefficient for channels and flood")
        p.put(72, 84, "plains of various kinds of bed material in the streams that were studied")
        p.row(100, [(72, "Material"), (250, "Size (mm)"), (400, "n value")])
        for i, (a, b, c) in enumerate(ROWS):
            p.row(112 + 12 * i, [(72, a), (250, b), (400, c)])
        t = p.tables()
        self.assertEqual(len(t), 1)
        self.assertIn("in the streams that were studied", t[0][0])
        self.assertIn("Cobble | 64-256 | 0.030", t[0])

    def test_two_tables_side_by_side_each_keep_their_own(self):
        p = self.page().put(54, 72, "Table 1. Values of n").put(320, 72, "Table 2. Gage data")
        p.row(88, [(54, "Site"), (140, "Year"), (220, "n"), (320, "Gage"), (400, "Q"), (480, "Stage")])
        for i in range(3):
            p.row(100 + 12 * i, [(54, "Creek %s" % "ABC"[i]), (140, "198%d" % i), (220, "0.03%d" % i),
                                 (320, "0%d" % (i + 1)), (400, "1%d0" % i), (480, "3.%d" % i)])
        t = p.tables()
        self.assertEqual([x[0] for x in t], ["Table (rows as printed): Table 1. Values of n",
                                             "Table (rows as printed): Table 2. Gage data"])
        self.assertIn("Creek A | 1980 | 0.030", t[0])
        self.assertIn("01 | 100 | 3.0", t[1])

    def test_a_table_on_a_page_a_degree_and_a_half_off_level(self):
        p = self.page()
        sk = 0.026                                   # 1.5 degrees
        p.put(72, 72, "Table 1. Base values of Manning's n", skew=sk)
        for i, (a, b, c) in enumerate(ROWS):
            p.row(90 + 11 * i, [(72, a), (250, b), (420, c)], skew=sk)
        rows = [r for t in p.tables() for r in t]
        self.assertIn("Cobble | 64-256 | 0.030", rows)

    def test_a_bare_all_capitals_caption(self):
        p = self.page().put(72, 72, "TABLE 2")
        p.row(88, [(72, "Material"), (250, "Size (mm)"), (400, "n value")])
        for i, (a, b, c) in enumerate(ROWS):
            p.row(100 + 12 * i, [(72, a), (250, b), (400, c)])
        self.assertIn("Cobble | 64-256 | 0.030", [r for t in p.tables() for r in t])

    def test_the_word_table_at_a_line_start_is_not_a_caption(self):
        for text in ("table was lower than in the year before", "TABLE OF CONTENTS", "Table of contents"):
            self.assertIsNone(self.vor._CAPTION.match(text), text)
        for text in ("Table 1. Base", "TABLE 3: Values", "Table A-1. Gages", "Table IV. Sites", "TABLE 2"):
            self.assertIsNotNone(self.vor._CAPTION.match(text), text)

    def test_equations_beside_a_left_column_table_stay_out_of_its_rows(self):
        p = self.page().prose(54, 40, 5).prose(320, 40, 5)
        p.put(54, 100, "Table 1. Base n values").put(320, 100, "The conveyance is computed from")
        p.row(114, [(54, "Material"), (150, "Size"), (230, "n")]).put(360, 114, "K = (1.486/n) A R^(2/3)")
        p.put(540, 114, "(4)")
        for i, (a, b, c) in enumerate(ROWS):
            p.row(126 + 12 * i, [(54, a), (150, b), (230, c)])
        p.put(360, 138, "Q = K S^(1/2)").put(540, 138, "(5)").put(320, 162, "where")
        p.prose(54, 180, 8).prose(320, 180, 8)
        rows = [r for t in self.page_tables(p) for r in t]
        self.assertIn("Material | Size | n", rows)
        self.assertIn("Boulder | >256 | 0.040", rows)
        self.assertFalse([r for r in rows if "K S" in r or "where" in r or "(4)" in r], rows)

    def test_a_description_column_that_starts_at_the_column_edge_is_kept(self):
        p = self.page().prose(54, 40, 5).prose(320, 40, 5)
        p.put(54, 100, "Table 2. Adjustment values")
        p.row(114, [(54, "Condition"), (180, "n value"), (320, "Example")])
        ex = ["compares to the smoothest channel in a bed material",
              "compares to carefully dredged channels in good shape",
              "compares to dredged channels with moderate roughness",
              "badly sloughed or scalloped banks of natural streams"]
        for i, (a, v) in enumerate([("Smooth", "0.000"), ("Minor", "0.001-0.005"), ("Moderate", "0.006-0.010"),
                                    ("Severe", "0.011-0.020")]):
            p.row(126 + 12 * i, [(54, a), (180, v), (320, ex[i])])
        p.prose(54, 190, 6).prose(320, 190, 6)
        rows = [r for t in self.page_tables(p) for r in t]
        self.assertIn("Smooth | 0.000 | " + ex[0], rows)

    def test_a_table_stops_at_the_references(self):
        p = self.page().put(72, 60, "Table 7. Verified n values")
        p.row(76, [(72, "Stream"), (250, "Year"), (400, "n")])
        for i, nm in enumerate(["Big Creek", "Salt Fork", "Deer Creek"]):
            p.row(88 + 12 * i, [(72, nm), (250, "198%d" % i), (400, "0.03%d" % i)])
        p.put(72, 140, "REFERENCES CITED")
        for i in range(3):
            p.row(156 + 12 * i, [(72, "Barnes, H.H., 196%d" % i), (250, "Roughness"), (400, "p. 1-%d" % (i + 2))])
        rows = [r for t in self.page_tables(p) for r in t]
        self.assertIn("Deer Creek | 1982 | 0.032", rows)
        self.assertFalse([r for r in rows if "Barnes" in r], rows)

    def page_tables(self, p):
        return [c.split("\n") for c in self.vor.layout_table_chunks(p.words, p.width)]

    def test_every_piece_of_a_long_table_repeats_its_column_headings(self):
        p = self.page().put(72, 40, "Table 9. Gage heights")
        p.row(56, [(72, "Gage"), (250, "Year"), (400, "Height (ft)")])
        for i in range(70):
            p.row(68 + 10 * i, [(72, "Gage on the river at mile %d" % i), (250, "19%02d" % i), (400, "%d.5" % i)])
        t = p.tables()
        self.assertGreater(len(t), 1)
        for piece in t:
            self.assertEqual(piece[1], "Gage | Year | Height (ft)")


class _Page:
    def __init__(self, n):
        self.n = n
        self.rect = types.SimpleNamespace(width=PAGES[str(n)]["width"]) if str(n) in PAGES else \
            types.SimpleNamespace(width=612.0)

    def get_text(self, kind="text"):
        p = PAGES.get(str(self.n))
        if kind == "words":
            return words(self.n) if p else []
        return p["text"] if p else "Plain running text with no table on this page at all.\n"

    def get_label(self):
        return ""

    def find_tables(self):
        return types.SimpleNamespace(tables=[])      # no ruling lines: the finder sees nothing


class _Doc:
    metadata = {}

    def __init__(self, path):
        self.pages = [_Page(n) for n in range(1, 16)]

    def __iter__(self):
        return iter(self.pages)

    def close(self):
        pass


class WiringTest(Base):
    """extract_pdf_tables falls back to the rows from word positions when the finder finds nothing on a page
    with a 'Table N' caption, and `vor tables --doc` puts them into an index built before 1.4.10."""

    def setUp(self):
        self.fake = types.ModuleType("pymupdf")
        self.fake.open = _Doc
        self.saved = {k: sys.modules.get(k) for k in ("pymupdf", "fitz")}
        sys.modules["pymupdf"] = self.fake

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def test_finder_empty_gives_layout_rows_on_captioned_pages_only(self):
        got = self.vor.extract_pdf_tables("wsp.pdf")
        self.assertEqual(sorted(got), [10, 15])
        self.assertIn("Cobble......... ........ | 64-256 | 0.030-0.050", got[10][0])

    def test_vor_tables_doc_reads_one_indexed_pdf_again(self):
        vor = self.vor
        pdf = os.path.join(self.home, "usgs-wsp-2339.pdf")
        open(pdf, "wb").close()
        db = vor.connect()
        try:
            cur = db.cursor()
            cur.execute("INSERT INTO docs(sha1,path,title,backend) VALUES(?,?,?,'pymupdf+tables')",
                        (vor.sha1_of(pdf), pdf, "Guide for Selecting Manning's Roughness Coefficients"))
            did = cur.lastrowid
            cur.execute("INSERT INTO docs(sha1,path,title,backend) VALUES('y',?,?,'pymupdf+tables')",
                        (os.path.join(self.home, "other.pdf"), "Other"))
            cur.execute("INSERT INTO chunks(doc_id,page,label,idx,txt,vec) VALUES(?,10,'',0,'scrambled',?)",
                        (did, b""))
            db.commit()
            vor._add_tables(db, only=[did])
            rows = db.execute("SELECT page, idx, txt FROM chunks WHERE doc_id=? ORDER BY page, idx",
                              (did,)).fetchall()
            self.assertEqual(rows[0], (10, 0, "scrambled"), "text passages are left as they are")
            tables = [r for r in rows if r[1] >= vor.TABLE_IDX]
            self.assertEqual(sorted({r[0] for r in tables}), [10, 15])
            vor._add_tables(db, only=[did])                 # a second run replaces, it does not add
            again = db.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=? AND idx>=?",
                               (did, vor.TABLE_IDX)).fetchone()[0]
            self.assertEqual(again, len(tables))
        finally:
            db.close()

    def test_vor_tables_doc_from_the_command_line(self):
        vor = self.vor
        pdf = os.path.join(self.home, "wsp-cli.pdf")
        open(pdf, "wb").close()
        db = vor.connect()
        try:
            cur = db.cursor()
            cur.execute("INSERT INTO docs(sha1,path,title,backend,number) VALUES('',?,'WSP','pymupdf+tables',"
                        "'WSP 2339')", (pdf,))
            did = cur.lastrowid
            db.commit()
        finally:
            db.close()
        vor.cmd_tables(argparse.Namespace(check=False, redo=False, again=False, doc="2339"))
        db = vor.connect()
        try:
            n = db.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=? AND idx>=?", (did, vor.TABLE_IDX)).fetchone()[0]
        finally:
            db.close()
        self.assertGreater(n, 0)
        with open(SRC, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('s.add_argument("--again"', src)
        self.assertIn('s.add_argument("--doc", metavar="KEY", help="read the tables', src)


class IndexSafetyTest(WiringTest):
    def test_a_changed_file_keeps_its_table_passages(self):
        vor = self.vor
        pdf = os.path.join(self.home, "changed.pdf")
        with open(pdf, "wb") as f:
            f.write(b"a different edition")
        db = vor.connect()
        try:
            cur = db.cursor()
            cur.execute("INSERT INTO docs(sha1,path,title,backend) VALUES('old-sha',?,'Changed','pymupdf+tables')",
                        (pdf,))
            did = cur.lastrowid
            cur.execute("INSERT INTO chunks(doc_id,page,label,idx,txt,vec) VALUES(?,3,'',?,'Table: kept',?)",
                        (did, vor.TABLE_IDX, b""))
            db.commit()
            vor._add_tables(db, only=[did])
            self.assertEqual(db.execute("SELECT txt FROM chunks WHERE doc_id=?", (did,)).fetchall(), [("Table: kept",)])
        finally:
            db.close()

    def test_plain_vor_tables_rereads_tables_read_before_1_4_10_and_doctor_says_so(self):
        vor = self.vor
        pdf = os.path.join(self.home, "old-tables.pdf")
        with open(pdf, "wb") as f:
            f.write(b"old tables")
        db = vor.connect()
        try:
            cur = db.cursor()
            cur.execute("INSERT INTO docs(sha1,path,title,backend) VALUES(?,?,'Old','pymupdf+tables')",
                        (vor.sha1_of(pdf), pdf))
            did = cur.lastrowid
            db.commit()
            vor._add_tables(db)
            self.assertEqual(db.execute("SELECT backend FROM docs WHERE id=?", (did,)).fetchone()[0],
                             vor.TABLES_BACKEND)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=? AND idx>=?",
                                          (did, vor.TABLE_IDX)).fetchone()[0], 0)
        finally:
            db.close()
        with open(SRC, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("had their tables read before Vor 1.4.10", src)

    def test_a_report_number_finds_its_document(self):
        vor = self.vor
        db = vor.connect()
        try:
            cur = db.cursor()
            cur.execute("INSERT INTO docs(sha1,path,title,number) VALUES('n1','/lib/usgs-wsp-2339.pdf','Guide',"
                        "'WSP 2339')")
            did = cur.lastrowid
            db.commit()
            ids, labels = vor.find_docs(db, "2339")
            self.assertIn(did, ids)
            ids, _ = vor.find_docs(db, str(did))
            self.assertEqual(ids, [did], "an id still names that document only")
            with self.assertRaises(SystemExit):
                vor.find_docs(db, "33")                # a short missing id is not a substring search
            with self.assertRaises(SystemExit):
                vor.find_docs(db, "233")               # nor is part of a number
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
