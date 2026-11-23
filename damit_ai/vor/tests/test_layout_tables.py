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
            cur.execute("INSERT INTO docs(sha1,path,title,backend) VALUES('x',?,?,'pymupdf+tables')",
                        (pdf, "Guide for Selecting Manning's Roughness Coefficients"))
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
            cur.execute("INSERT INTO docs(sha1,path,title,backend) VALUES('cli',?,'WSP','pymupdf+tables')", (pdf,))
            did = cur.lastrowid
            db.commit()
        finally:
            db.close()
        vor.cmd_tables(argparse.Namespace(check=False, redo=False, again=False, doc="wsp-cli"))
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


if __name__ == "__main__":
    unittest.main()
