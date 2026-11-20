"""Wire-contract tests for the ND GIS Hub imagery-dates query (core/basemap.imagery_dates,
audit 2026-11-20).

The load-bearing contract: Imagery/Dates_Imagery MapServer/41 /query answers
{features: [{attributes: {IDATE: ...}}]}; IDATE comes in several formats that
parse_date normalises to YYYY-MM-DD; a service outage or redesign must degrade to
[] (a hillshade-with-no-date QA map) — never an exception in the map builder and
never a silent wrong date.

Fixtures are a REAL capture (query_naip_dates_feature.json, taken 2026-11-20 from the
live public service over a Fargo-area box) plus deliberate near-miss decoys.

Run:  python -m unittest damit_runner.tests.test_ndgishub_wire
"""
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from damit_runner.core import basemap as BM            # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures_ndgishub")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


class FakeNet(object):
    """The transport seam imagery_dates is given (it calls net.get(url, 'json'))."""

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.urls = []
        self.failures = []

    def get(self, url, kind, timeout=10.0):
        self.urls.append(url)
        return self.body


SRC = {"date_service": "naip:" + BM.NAIP_2025_DATES_URL}
# a WGS84 box so _lonlat_bbox is the identity (EPSG:4326 wkt)
WKT4326 = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
           'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,'
           'AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,'
           'AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]')
BBOX = (-97.2, 46.8, -97.1, 46.9)


class RealCapture(unittest.TestCase):
    def test_dates_from_the_live_answer(self):
        net = FakeNet(load("query_naip_dates_feature.json"))
        with mock.patch.object(BM, "_lonlat_bbox", return_value=BBOX):
            dates = BM.imagery_dates(SRC, BBOX, WKT4326, net)
        self.assertEqual(dates, ["2025-07-13"])          # 4 seamlines, one flight date
        # the request itself must ask the pinned layer with the pinned query contract
        url = net.urls[0]
        self.assertIn("Dates_Imagery/MapServer/41/query", url)
        for needle in ("outFields=IDATE", "returnGeometry=false", "f=json",
                       "geometryType=esriGeometryEnvelope", "inSR=4326"):
            self.assertIn(needle, url, needle)


class ParseDateContract(unittest.TestCase):
    def test_all_documented_formats(self):
        self.assertEqual(BM.parse_date("2025-07-13"), "2025-07-13")
        self.assertEqual(BM.parse_date("7/13/2025"), "2025-07-13")
        self.assertEqual(BM.parse_date("20250713"), "2025-07-13")
        self.assertEqual(BM.parse_date("2025-7-3"), "2025-07-03")   # 1-digit month/day
        self.assertIsNone(BM.parse_date("not a date"))
        self.assertIsNone(BM.parse_date(""))
        self.assertIsNone(BM.parse_date(None))
        self.assertIsNone(BM.parse_date("13/2025/07"))              # day-first nonsense


class DriftDecoys(unittest.TestCase):
    def _dates(self, name):
        net = FakeNet(load(name))
        with mock.patch.object(BM, "_lonlat_bbox", return_value=BBOX):
            return BM.imagery_dates(SRC, BBOX, WKT4326, net), net

    def test_renamed_field_degrades_to_no_dates(self):
        dates, _ = self._dates("decoy_renamed_field.json")
        self.assertEqual(dates, [], "a renamed IDATE must mean 'no dates', never a crash")

    def test_emptied_layer_degrades_to_no_dates(self):
        dates, _ = self._dates("decoy_no_features.json")
        self.assertEqual(dates, [])

    def test_html_error_degrades_to_no_dates(self):
        dates, net = self._dates("decoy_html_error.html")
        self.assertEqual(dates, [])
        self.assertTrue(any("dates" in f for f in net.failures),
                        "the outage must be recorded in net.failures, not swallowed silently")

    def test_mixed_formats_deduped_and_sorted(self):
        dates, _ = self._dates("decoy_mixed_formats.json")
        self.assertEqual(dates, ["2025-07-13", "2025-07-14", "2025-07-15"])
        self.assertEqual(dates, sorted(set(dates)))

    def test_esri_identify_branch_reads_SRC_DATE(self):
        identify = {"results": [{"attributes": {"DATE (YYYYMMDD)": "20241002"}},
                                {"attributes": {"SRC_DATE": "10/15/2023"}}]}
        src = {"date_service": "esri:" + BM.ESRI_IMAGERY_IDENTIFY}
        net = FakeNet(json.dumps(identify))
        with mock.patch.object(BM, "_lonlat_bbox", return_value=BBOX):
            dates = BM.imagery_dates(src, BBOX, WKT4326, net)
        self.assertEqual(dates, ["2023-10-15", "2024-10-02"])

    def test_unsupported_source_kind_answers_empty(self):
        net = FakeNet("{}")
        with mock.patch.object(BM, "_lonlat_bbox", return_value=BBOX):
            self.assertEqual(BM.imagery_dates({"date_service": ""}, BBOX, WKT4326, net), [])


if __name__ == "__main__":
    unittest.main()
