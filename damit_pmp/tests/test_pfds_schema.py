"""Schema-drift tests for the NOAA HDSC PFDS answer (atlas14.parse), audit 2026-11-20.

The load-bearing provider contract (48 references across the suite): the PFDS page at
hdsc.nws.noaa.gov answers a small quasi-JS text whose parts atlas14.parse lifts with two
regexes (_SCALAR name='value'; _ARRAY name=[[...]];) plus a dimension check. The real
captures live in fixtures/ (test_atlas14.py pins the happy paths and CoverageError);
these tests pin the FAILURE side - what must happen when NOAA changes the page.

Every decoy in fixtures_drift/ mutates one thing about the real Fargo PDS capture. A
parser change that turns any of these loud failures into a silent wrong answer fails
here.

Run:  python -m unittest damit_pmp.tests.test_pfds_schema
"""
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys = None
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from damit_pmp import atlas14 as A                                    # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures_drift")


def decoy(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


class GoodAnswerStillParses(unittest.TestCase):
    """The real Fargo capture (the decoys' base) must keep parsing: 19 x 10 PDS."""

    def test_real_capture_dims_and_metadata(self):
        with open(os.path.join(HERE, "fixtures", "pfds_pds_english_fargo_nd.txt"), encoding="utf-8") as fh:
            pf = A.parse(fh.read())
        self.assertEqual(len(pf["quantiles"]), 19)
        self.assertTrue(all(len(r) == 10 for r in pf["quantiles"]))
        self.assertEqual(pf["frequencies"], [1, 2, 5, 10, 25, 50, 100, 200, 500, 1000])
        self.assertEqual(pf["durations"][9], "24-hr")
        self.assertEqual(pf["volume"], "8")
        self.assertEqual(pf["series"], "pds")
        self.assertEqual(pf["units"], "english")
        # monotone in both directions on the 24-hr row (sanity of the numbers themselves)
        row = pf["quantiles"][9]
        self.assertEqual(row, sorted(row))
        # upper/lower bound the quantiles
        for q, u, l in zip(pf["quantiles"][9], pf["upper"][9], pf["lower"][9]):
            self.assertLessEqual(l, q)
            self.assertLessEqual(q, u)


class DriftDecoys(unittest.TestCase):
    def test_html_error_page_is_not_parsed_as_numbers(self):
        with self.assertRaises(A.Atlas14Error) as ctx:
            A.parse(decoy("pfds_html_error_page.html"))
        # must name the problem, not quote a number-looking substring silently
        self.assertNotIn("0.330", str(ctx.exception))

    def test_renamed_quantiles_variable_breaks_loudly(self):
        with self.assertRaises(A.Atlas14Error) as ctx:
            A.parse(decoy("pfds_renamed_quantiles.txt"))
        self.assertIn("durations", str(ctx.exception).lower())

    def test_missing_duration_row_reports_both_dims(self):
        with self.assertRaises(A.Atlas14Error) as ctx:
            A.parse(decoy("pfds_row_dropped.txt"))
        msg = str(ctx.exception)
        self.assertIn("18", msg)
        self.assertIn("19", msg)

    def test_error_msg_refusal_carries_noaas_message(self):
        with self.assertRaises(A.Atlas14Error) as ctx:
            A.parse(decoy("pfds_error_msg_refusal.txt"))
        self.assertIn("offline for maintenance", str(ctx.exception))

    def test_nonnumeric_cell_refuses_whole_parse(self):
        with self.assertRaises(A.Atlas14Error) as ctx:
            A.parse(decoy("pfds_nonnumeric_cell.txt"))
        self.assertIn("cannot read", str(ctx.exception).lower())

    def test_coverage_refusal_is_coverageerror_not_generic(self):
        with open(os.path.join(HERE, "fixtures", "pfds_no_coverage_portland_or.txt"), encoding="utf-8") as fh:
            with self.assertRaises(A.CoverageError) as ctx:
                A.parse(fh.read())
        self.assertIn("does not cover", str(ctx.exception))


class CachePoisoningGuard(unittest.TestCase):
    """A drifted answer must never be written into the on-disk cache."""

    def _fetch(self, text, tmp):
        class Http:
            def get_bytes(self, url, timeout=60):
                return text.encode("utf-8")

        return A.fetch(46.8772, -96.7898, Http(), cache_dir=tmp, offline=False)

    def test_refusal_not_cached(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(A.Atlas14Error):
                self._fetch(decoy("pfds_error_msg_refusal.txt"), tmp)
            self.assertEqual(os.listdir(tmp), [], "a refused answer must not be cached")


if __name__ == "__main__":
    unittest.main()
