"""The NID-by-state inventory (damit_desktop/nid.py) and its endpoint. Fixtures only; never downloads the NID."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from damit_desktop import nid  # noqa: E402

RI = (HERE / "fixtures" / "nid_ri_fixture.csv").read_text(encoding="utf-8")
ND = (HERE.parent.parent / "scripts" / "fixtures" / "nid_nd_fixture.csv").read_text(encoding="utf-8")


class ConvertTests(unittest.TestCase):
    def test_rhode_island_main_dams_only_no_owner_text(self):
        b = nid.convert_csv(RI, "ri", "2026-11-09T00:00:00Z")
        self.assertEqual(b["v"], 2)
        self.assertEqual(b["cols"], nid.COLS)
        self.assertEqual(b["source"]["state"], "RI")
        self.assertIn("stateKey%3ARI&out=csv", b["source"]["url"])
        ids = [r[0] for r in b["rows"]]
        self.assertEqual(len(ids), 5)
        self.assertTrue(all(nid.NID_ID_RE.fullmatch(i) and i.startswith("RI") for i in ids), ids)
        self.assertEqual(len(b["source"]["dropped"]), 1, "the associated structure is dropped")
        text = json.dumps(b)
        self.assertNotIn("FIXTURE-OWNER-NOT-REAL", text)
        self.assertNotIn("FIXTURE-DESIGNER-NOT-REAL", text)
        self.assertNotIn('"owner', text.lower())
        self.assertIn("National Inventory of Dams", b["source"]["attribution"])

    def test_nd_fixture_matches_the_node_build_values(self):
        b = nid.convert_csv(ND, "ND", "2026-10-29T21:56:00Z")
        rows = {r[0]: dict(zip(b["cols"], r)) for r in b["rows"]}
        self.assertEqual(len(rows), 8)
        d = rows["ND00199"]
        self.assertEqual((d["name"], d["nidHeightFt"], d["nidStorageAcFt"], d["lengthFt"]), ("Swan Buffalo Detention Dam 12", 28, 1615.5, 1700))
        self.assertIsNone(rows["ND90001"]["maxStorageAcFt"])
        self.assertIsNone(rows["ND90002"]["lengthFt"], "zero is missing, never 0")
        self.assertEqual((rows["ND00001"]["nidHeightFt"], rows["ND00001"]["damHeightFt"]), (24, 16))

    def test_bad_input(self):
        with self.assertRaises(nid.NidError):
            nid.state_code("North Dakota")
        with self.assertRaises(nid.NidError):
            nid.state_code("ZZ")
        with self.assertRaisesRegex(nid.NidError, "schema changed"):
            nid.convert_csv(RI.replace("NID Height (Ft)", "NID Height", 1), "RI")
        with self.assertRaisesRegex(nid.NidError, "no main dams"):
            nid.convert_csv(RI.splitlines()[0] + "\n", "RI")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "settings" / "nid"
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url):
        self.calls.append(url)
        return RI

    def test_downloads_once_then_reads_the_cache_and_refresh_downloads_again(self):
        a = nid.load_state("RI", fetch=self.fetch, folder=self.dir)
        b = nid.load_state("RI", fetch=self.fetch, folder=self.dir)
        self.assertEqual(a["rows"], b["rows"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0], "https://nid.sec.usace.army.mil/api/query?sy=%40stateKey%3ARI&out=csv")
        self.assertTrue((self.dir / "nid_RI.json").is_file())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["nid_RI.json"], "no raw CSV kept")
        nid.load_state("RI", refresh=True, fetch=self.fetch, folder=self.dir)
        self.assertEqual(len(self.calls), 2)

    def test_a_damaged_cache_is_downloaded_again(self):
        self.dir.mkdir(parents=True)
        (self.dir / "nid_RI.json").write_text("{not json", encoding="utf-8")
        nid.load_state("RI", fetch=self.fetch, folder=self.dir)
        self.assertEqual(len(self.calls), 1)

    def test_an_http_502_from_the_nid_is_an_error_naming_the_status(self):
        import io
        import urllib.error
        from unittest import mock

        def boom(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, io.BytesIO(b""))

        with mock.patch("urllib.request.urlopen", side_effect=boom):
            with self.assertRaisesRegex(nid.NidError, r"HTTP 502 Bad Gateway"):
                nid._download("https://nid.sec.usace.army.mil/api/query?sy=%40stateKey%3ARI&out=csv")

    def test_a_failed_download_is_an_error_and_caches_nothing(self):
        def down(url):
            raise nid.NidError("the NID download failed (offline)")

        with self.assertRaisesRegex(nid.NidError, "offline"):
            nid.load_state("RI", fetch=down, folder=self.dir)
        self.assertFalse((self.dir / "nid_RI.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
