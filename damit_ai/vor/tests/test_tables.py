"""Vor 1.4.0: tables read as tables.

Why this exists: a table on a PDF page became running text, so a row's numbers lost their column headings
(a Manning n table read "0.025 0.030 0.033 ..."), and questions about values in tables (Manning n, breach
parameters, hazard classes) are much of what Vor is asked. The Markdown helpers need nothing; the PDF test
needs PyMuPDF and is skipped without it (the cloud CI has none). No model: embeddings are stubbed.
"""
import argparse
import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "vor.py")
try:
    import pymupdf
except ImportError:
    pymupdf = None


def load(home):
    old = {k: os.environ.get(k) for k in ("VOR_HOME", "VOR_DB")}
    os.environ["VOR_HOME"] = home
    os.environ["VOR_DB"] = os.path.join(home, "vor.db")
    try:
        spec = importlib.util.spec_from_file_location("vor_tables_under_test", SRC)
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


ROWS = [["Channel", "Minimum", "Normal", "Maximum"],
        ["Clean, straight", "0.025", "0.030", "0.033"],
        ["Clean, winding", "0.033", "0.040", "0.045"],
        ["Sluggish, weedy", "0.050", "0.070", "0.080"],
        ["Very weedy", "0.075", "0.100", "0.150"]]


class MarkdownTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vor-tables-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.vor = load(os.path.join(self.tmp, "Vor"))

    def test_a_row_keeps_its_column_headings(self):
        md = self.vor.table_markdown(ROWS)
        self.assertTrue(md.startswith("| Channel | Minimum | Normal | Maximum |"))
        self.assertIn("| Clean, winding | 0.033 | 0.040 | 0.045 |", md)

    def test_not_a_table(self):
        self.assertEqual(self.vor.table_markdown([["just one row", "x"]]), "")
        self.assertEqual(self.vor.table_markdown([["a"], ["b"], ["c"]]), "")

    def test_a_long_table_is_split_between_rows_with_the_header_on_each_piece(self):
        rows = [["Station", "Depth ft"]] + [["%d+00" % i, "%.2f" % (i / 7.0)] for i in range(400)]
        pieces = self.vor.table_chunks("Table 4. Depths", self.vor.table_markdown(rows))
        self.assertGreater(len(pieces), 1)
        for p in pieces:
            self.assertTrue(p.startswith("Table: Table 4. Depths\n| Station | Depth ft |\n|---|---|\n"))
            self.assertLessEqual(len(p), self.vor.CHUNK_MAX + 60)
        self.assertEqual(sum(p.count("+00 |") for p in pieces), 400)


@unittest.skipIf(pymupdf is None, "PyMuPDF not installed")
class PdfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vor-tables-pdf-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Vor")
        self.vor = load(self.home)
        os.makedirs(self.vor.LIBRARY)
        self.pdf = os.path.join(self.vor.LIBRARY, "chow-table.pdf")
        d = pymupdf.open()
        pg = d.new_page()
        pg.insert_text((72, 60), "Open-channel hydraulics, chapter 5. Values of the roughness coefficient n "
                                 "for natural streams.", fontsize=9)
        pg.insert_text((72, 100), "Table 5-6. Values of the roughness coefficient n", fontsize=10)
        x0, y0, w, h = 72, 110, 110, 22
        for r, row in enumerate(ROWS):
            for c, cell in enumerate(row):
                rect = pymupdf.Rect(x0 + c * w, y0 + r * h, x0 + (c + 1) * w, y0 + (r + 1) * h)
                pg.draw_rect(rect, color=(0, 0, 0), width=0.8)
                pg.insert_text((rect.x0 + 4, rect.y0 + 15), cell, fontsize=9)
        d.save(self.pdf)
        d.close()

    def test_ingest_stores_the_table_as_its_own_passage(self):
        self.vor.cmd_ingest(argparse.Namespace(paths=[], prune=False))
        db = self.vor.connect()
        try:
            rows = db.execute("SELECT idx, txt FROM chunks WHERE idx >= ?", (self.vor.TABLE_IDX,)).fetchall()
            backend = db.execute("SELECT backend FROM docs").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(backend, "pymupdf+tables")
        self.assertEqual(len(rows), 1)
        self.assertIn("Table 5-6", rows[0][1])
        self.assertIn("| Clean, winding | 0.033 | 0.040 | 0.045 |", rows[0][1])

    def test_vor_tables_adds_them_to_an_older_index_once(self):
        real = self.vor.extract_pdf_tables
        self.vor.extract_pdf_tables = lambda path, pages_text=None: {}
        self.vor.cmd_ingest(argparse.Namespace(paths=[], prune=False))
        self.vor.extract_pdf_tables = real
        db = self.vor.connect()
        db.execute("UPDATE docs SET backend='pymupdf'")          # as 1.3.x left it
        db.commit()
        db.close()
        self.assertTrue(any("vor tables" in t for l, t in self.vor.library_checks()))
        self.vor.cmd_tables(argparse.Namespace())
        self.vor.cmd_tables(argparse.Namespace())                # nothing left to do the second time
        db = self.vor.connect()
        try:
            n = db.execute("SELECT COUNT(*) FROM chunks WHERE idx >= ?", (self.vor.TABLE_IDX,)).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(n, 1)
        self.assertFalse(any("vor tables" in t for l, t in self.vor.library_checks()))
        db = self.vor.connect()
        try:
            hits = self.vor.Index(db).search("Clean winding roughness Normal", k=3)
        finally:
            db.close()
        self.assertTrue(any("0.040" in h.txt and "Normal" in h.txt for h in hits))


if __name__ == "__main__":
    unittest.main()
