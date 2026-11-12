"""DamIT PMP Atlas 14 client (pure Python; recorded PFDS answers, no network)."""
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from damit_pmp import atlas14 as A  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


FARGO = fixture("pfds_pds_english_fargo_nd.txt")
LINCOLN = fixture("pfds_ams_metric_lincoln_ne.txt")
PORTLAND = fixture("pfds_no_coverage_portland_or.txt")


class FakePFDS(object):
    def __init__(self, answer):
        self.answer, self.urls = answer, []

    def get_bytes(self, url, timeout=60):
        self.urls.append(url)
        return self.answer(url) if callable(self.answer) else self.answer


class Parse(unittest.TestCase):
    def test_pds_english(self):
        pf = A.parse(FARGO)
        self.assertEqual((pf["volume"], pf["version"], pf["region"]), ("8", "2", "Midwestern States"))
        self.assertEqual(pf["frequencies"], [1, 2, 5, 10, 25, 50, 100, 200, 500, 1000])
        self.assertEqual(len(pf["quantiles"]), 19)
        self.assertEqual(pf["quantiles"][A.duration_index("24-hr")][A.freq_index(pf, 100)], 6.47)
        self.assertEqual(pf["upper"][0][0], 0.418)
        self.assertEqual(pf["unit_label"], "in")
        self.assertIn("NOAA Atlas 14 Volume 8 Version 2", A.citation(pf))
        self.assertEqual(len(A.table_rows(pf)), 190)

    def test_ams_metric(self):
        pf = A.parse(LINCOLN)
        self.assertEqual(pf["series"], "ams")
        self.assertEqual(pf["frequencies"], [2, 5, 10, 25, 50, 100, 200, 500, 1000])
        self.assertEqual(pf["unit_label"], "mm")
        with self.assertRaises(A.Atlas14Error):
            A.freq_index(pf, 1)                       # no 1-year AEP in AMS

    def test_no_coverage_fails_clearly(self):
        with self.assertRaises(A.CoverageError) as cm:
            A.parse(PORTLAND)
        self.assertIn("does not cover this location", str(cm.exception))

    def test_garbage(self):
        with self.assertRaises(A.Atlas14Error):
            A.parse(b"<html>503</html>")
        with self.assertRaises(A.Atlas14Error):
            A.parse(b"result = 'values';\nquantiles = [['1']];\n")


class Fetch(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.cache)

    def test_url_and_cache(self):
        http = FakePFDS(FARGO)
        pf, src = A.fetch(46.8772, -96.7898, http, self.cache)
        self.assertTrue(http.urls[0].startswith("https://hdsc.nws.noaa.gov/cgi-bin/new/cgi_readH5.py?lat=46.8772"))
        self.assertIn("series=pds", http.urls[0])
        self.assertFalse(src["from_cache"])
        self.assertEqual(src["source"], "NOAA Atlas 14 (PFDS)")
        pf2, src2 = A.fetch(46.8772, -96.7898, http, self.cache)
        self.assertTrue(src2["from_cache"])
        self.assertEqual(len(http.urls), 1)
        self.assertEqual(pf2["quantiles"], pf["quantiles"])
        _, off = A.fetch(46.8772, -96.7898, None, self.cache, offline=True)
        self.assertTrue(off["from_cache"])
        with self.assertRaises(A.Atlas14Error):
            A.fetch(47.0, -97.0, None, self.cache, offline=True)

    def test_no_coverage_not_cached(self):
        http = FakePFDS(PORTLAND)
        with self.assertRaises(A.CoverageError):
            A.fetch(45.52, -122.68, http, self.cache)
        self.assertEqual(os.listdir(self.cache), [])

    def test_polite_many(self):
        waits = []
        http = FakePFDS(FARGO)
        A.fetch_many([(46.0, -97.0), (46.1, -97.0), (46.0, -97.0)], http, self.cache, pause_s=1.0, sleep=waits.append)
        self.assertEqual(len(http.urls), 2)          # third point from the cache
        self.assertEqual(waits, [1.0, 1.0])

    def test_bad_arguments(self):
        with self.assertRaises(A.Atlas14Error):
            A.query_url(95, 0)
        with self.assertRaises(A.Atlas14Error):
            A.query_url(45, -100, series="hms")


class Derived(unittest.TestCase):
    def test_interpolation_exact_and_between(self):
        pf = A.parse(FARGO)
        j = A.freq_index(pf, 100)
        self.assertEqual(A.depth_at(pf, 1440, 100), 6.47)
        d90 = A.depth_at(pf, 90, 100)
        self.assertTrue(pf["quantiles"][4][j] < d90 < pf["quantiles"][5][j])
        with self.assertRaises(A.Atlas14Error):
            A.depth_at(pf, 2, 100)
        with self.assertRaises(A.Atlas14Error):
            A.depth_at(pf, 100000, 100)

    def test_alternating_block(self):
        pf = A.parse(FARGO)
        rows = A.alternating_block(pf, 100, 1440, 60)
        self.assertEqual(len(rows), 24)
        self.assertAlmostEqual(rows[-1][2], 6.47, places=3)
        incs = [r[1] for r in rows]
        self.assertEqual(incs.index(max(incs)), 11)
        self.assertAlmostEqual(max(incs), A.depth_at(pf, 60, 100), places=3)
        # every centred 3-step window holds the 3-hour depth
        self.assertAlmostEqual(sum(incs[10:13]), A.depth_at(pf, 180, 100), places=3)
        with self.assertRaises(A.Atlas14Error):
            A.alternating_block(pf, 100, 1440, 7)

    def test_one_duration_list_everywhere(self):
        from damit_pmp import gisgrid as G
        self.assertIs(G.DURATION_LABELS, A.DURATION_LABELS)                 # one constant, not copies
        self.assertEqual(len(A.DURATION_LABELS), 19)
        self.assertEqual(A.DURATION_LABELS[A.DEFAULT_DURATION_INDEX], "24-hr")
        self.assertEqual(A.DEFAULT_DURATION_INDEX, 9)
        self.assertEqual(A.DURATION_LABELS, [d for d, _ in A.DURATIONS])
        self.assertEqual((A.duration_minutes("5-min"), A.duration_minutes("24-hr"), A.duration_minutes("60-day")),
                         (5, 1440, 86400))

    def test_every_duration_builds_or_says_why(self):
        pf = A.parse(FARGO)
        for label, minutes in A.DURATIONS:
            with self.assertRaises(A.Atlas14Error) as cm:                   # a 90-min step never fits the short ones
                A.alternating_block(pf, 100, minutes, 90 if minutes % 90 else minutes * 2)
            self.assertTrue(any(w in str(cm.exception) for w in ("shorter than the time step", "whole number")), label)
            step = 5 if minutes < 60 else 60
            rows = A.alternating_block(pf, 100, minutes, step)
            self.assertEqual(len(rows), minutes // step, label)
            self.assertAlmostEqual(rows[-1][2], A.depth_at(pf, minutes, 100), places=3, msg=label)

    def test_check_storm_messages(self):
        with self.assertRaises(A.Atlas14Error) as cm:
            A.check_storm(5, 60, "5-min")
        self.assertIn("5-min (5 min) is shorter than the time step of 60 min", str(cm.exception))
        self.assertIn("5 min or less", str(cm.exception))
        with self.assertRaises(A.Atlas14Error) as cm:
            A.check_storm(1440, 7, "24-hr")
        self.assertIn("divides 1440 min", str(cm.exception))
        with self.assertRaises(A.Atlas14Error) as cm:
            A.check_storm(86400, 5, "60-day")                               # 17280 blocks is fine ...
            A.check_storm(86400 * 2, 5)                                     # ... 34560 is not
        self.assertIn("at most 20000", str(cm.exception))
        with self.assertRaises(A.Atlas14Error):
            A.check_storm(60, 2)

    def test_combine(self):
        a, b = A.parse(FARGO), A.parse(FARGO)
        b = dict(b, quantiles=[[v * 2 for v in row] for row in b["quantiles"]])
        m = A.combine([a, b], "mean")
        self.assertAlmostEqual(m["quantiles"][9][6], 6.47 * 1.5, places=3)
        self.assertEqual(A.combine([a, b], "max")["quantiles"][9][6], 12.94)
        with self.assertRaises(A.Atlas14Error):
            A.combine([a, A.parse(LINCOLN)])


class Atlas14Only(unittest.TestCase):
    """No non-Atlas-14 PMP source or data ships in the plugin."""

    def test_no_foreign_pmp_sources(self):
        bad = re.compile(r"(\bAWA\b|Applied Weather|\bHMS\b|HMSv|\bHMR\b|\.gdb\b|pmp_evaluation|ND_PMP|SWC)", re.I)
        allowed_text = ("metadata.txt", "README.md")
        for base, dirs, files in os.walk(os.path.join(ROOT, "damit_pmp")):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                p = os.path.join(base, f)
                self.assertFalse(f.lower().endswith((".gdb", ".gpkg", ".zip", ".nc", ".h5")), p)
                if f in allowed_text or f.endswith((".svg", ".pyc")) or os.path.basename(base) == "tests":
                    continue
                with open(p, encoding="utf-8", errors="replace") as fh:
                    self.assertIsNone(bad.search(fh.read()), p)

    def test_only_pfds_host(self):
        hosts = set()
        for base, dirs, files in os.walk(os.path.join(ROOT, "damit_pmp")):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(base, f), encoding="utf-8") as fh:
                        hosts |= set(re.findall(r"https?://([^/\s\"']+)", fh.read()))
        self.assertEqual(hosts, {"hdsc.nws.noaa.gov"})


if __name__ == "__main__":
    unittest.main()
