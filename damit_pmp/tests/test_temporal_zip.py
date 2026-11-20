"""DamIT PMP temporal.py: the NOAA HDSC temporal-area shapefile zip is extracted only when it is safe
(audit 2026-11-19, re-synced from DamSafety PMP). Pure Python, no QGIS, no GDAL, no network."""
import io
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from damit_pmp import temporal as T  # noqa: E402


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


class SafeExtract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def test_plain_members_are_extracted(self):
        T._safe_extract_zip(_zip({"area.shp": b"x", "sub/area.dbf": b"y"}), self.dest)
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "area.shp")))
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "sub", "area.dbf")))

    def test_unsafe_paths_are_refused(self):
        for bad in ("../evil.shp", "/abs/evil.shp", "C:/evil.shp", "a/../../evil.shp", "a\\..\\..\\evil.shp"):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                T._safe_extract_zip(_zip({bad: b"x"}), self.dest)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "evil.shp")))

    def test_size_cap(self):
        old = T._ZIP_MAX_TOTAL
        T._ZIP_MAX_TOTAL = 10
        try:
            with self.assertRaises(RuntimeError):
                T._safe_extract_zip(_zip({"big.shp": b"x" * 11}), self.dest)
        finally:
            T._ZIP_MAX_TOTAL = old
        self.assertFalse(os.path.exists(os.path.join(self.dest, "big.shp")))

    def test_torn_cache_is_cleared(self):
        os.makedirs(self.dest)
        open(os.path.join(self.dest, "half.shp"), "w").close()
        T._clear_torn_cache(self.dest)
        self.assertFalse(os.path.exists(self.dest))


if __name__ == "__main__":
    unittest.main()
