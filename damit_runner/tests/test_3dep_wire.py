"""Wire-contract tests for the USGS 3DEP exportImage refill (core/dem_refill.fetch_3dep),
audit 2026-11-20.

The load-bearing failure mode: the ArcGIS ImageServer can answer an HTML/JSON error page
WITH HTTP 200, so the download layer cannot trust the status code. fetch_3dep validates
the ANSWER ITSELF before writing anything: the TIFF magic leaders (classic + BigTIFF),
a minimum real-tile length, and never leaving a partial file at out_path (the write goes
through .part + os.replace). These tests pin all three guards and the retry policy
(transport errors retried; deterministic bad answers never are).

The happy-path fixture is a real, tiny 3DEP-shaped TIFF written byte-exact in the test
(no network, no GDAL needed to build it): a 2x2 Float32 classic little-endian TIFF.

Run:  python -m unittest damit_runner.tests.test_3dep_wire
"""
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from damit_runner.core import dem_refill as DR        # noqa: E402
from damit_runner.compat import netproxy as _netproxy  # noqa: E402


def tiny_tiff():
    """A minimal valid classic little-endian TIFF (II*), 2x2 Float32, ~1.4 KB.

    Enough IFD structure to be a plausible tile: an image header, one IFD with
    the image-width/height/bits/sample-strip-offset entries, and padded pixel data,
    so its length clears DR.MIN_TILE_BYTES and its first 4 bytes are II*\\x00.
    """
    # TIFF header (II, magic 42, IFD at offset 8)
    out = bytearray(b"II*\x00\x08\x00\x00\x00")
    # 10 IFD entries (12 bytes each) + next-IFD pointer
    n_entries = 10
    entries_len = 2 + n_entries * 12 + 4
    strip_data_offset = 8 + entries_len
    pixels = struct.pack("<8f", 480.0, 481.0, 480.5, 479.5, 480.2, 481.1, 480.7, 479.9)
    def entry(tag, typ, count, value):
        return struct.pack("<HHI4s", tag, typ, count, value)
    entries = b""
    entries += entry(256, 3, 1, struct.pack("<H", 2) + b"\x00\x00")          # ImageWidth
    entries += entry(257, 3, 1, struct.pack("<H", 2) + b"\x00\x00")          # ImageLength
    entries += entry(258, 3, 1, struct.pack("<H", 32) + b"\x00\x00")         # BitsPerSample
    entries += entry(259, 3, 1, struct.pack("<H", 1) + b"\x00\x00")          # Compression none
    entries += entry(262, 3, 1, struct.pack("<H", 1) + b"\x00\x00")          # Photometric
    entries += entry(273, 4, 1, struct.pack("<I", strip_data_offset))        # StripOffsets
    entries += entry(277, 3, 1, struct.pack("<H", 1) + b"\x00\x00")          # SamplesPerPixel
    entries += entry(278, 4, 1, struct.pack("<I", 4))                        # RowsPerStrip
    entries += entry(279, 4, 1, struct.pack("<I", len(pixels)))              # StripByteCounts
    entries += entry(284, 3, 1, struct.pack("<H", 1) + b"\x00\x00")          # PlanarConfig
    ifd = struct.pack("<H", n_entries) + entries + struct.pack("<I", 0)
    data = bytes(out) + ifd + pixels
    # pad so the total clears MIN_TILE_BYTES without lying about the format
    data += b"\x00" * max(0, DR.MIN_TILE_BYTES + 8 - len(data))
    assert data[:4] == b"II*\x00" and len(data) >= DR.MIN_TILE_BYTES
    return data


class AnswerValidation(unittest.TestCase):
    def _fetch(self, answer_bytes, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "tile.tif")
            with mock.patch.object(_netproxy, "urlopen", _one_shot(answer_bytes)):
                DR.fetch_3dep((0.0, 0.0, 20.0, 20.0), 10.0, out, **kw)
            with open(out, "rb") as fh:
                return fh.read()

    def test_good_tiff_lands_whole(self):
        data = self._fetch(tiny_tiff())
        self.assertEqual(data[:4], b"II*\x00")

    def test_html_error_page_with_http_200_is_refused(self):
        html = b"<html><body>{\"error\":{\"code\":500}}</body></html>"
        with self.assertRaises(IOError) as ctx:
            self._fetch(html)
        self.assertIn("did not return a GeoTIFF", str(ctx.exception))

    def test_short_answer_is_refused(self):
        with self.assertRaises(IOError) as ctx:
            self._fetch(b"II*\x00" + b"\x00" * 40)
        self.assertIn("short answer", str(ctx.exception))

    def test_bigtiff_magic_accepted(self):
        le_big = b"II+\x00" + b"\x00" * 1100
        data = self._fetch(le_big)
        self.assertEqual(data[:4], b"II+\x00")

    def test_no_partial_file_left_behind(self):
        """A bad answer must not leave tile.tif NOR tile.tif.part on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "tile.tif")
            with mock.patch.object(_netproxy, "urlopen", _one_shot(b"<html>x</html>")):
                with self.assertRaises(IOError):
                    DR.fetch_3dep((0.0, 0.0, 20.0, 20.0), 10.0, out)
            self.assertEqual(sorted(os.listdir(tmp)), [],
                             "no tile and no .part may survive a refused answer")

    def test_transport_failure_retried_then_reported(self):
        calls = []

        class Boom(Exception):
            pass

        def flaky(req, timeout=10):
            calls.append(1)
            raise Boom("connection reset")

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(_netproxy, "urlopen", flaky), \
                    mock.patch.object(DR.time, "sleep", lambda s: None):
                with self.assertRaises(IOError) as ctx:
                    DR.fetch_3dep((0.0, 0.0, 20.0, 20.0), 10.0, os.path.join(tmp, "t.tif"))
        self.assertEqual(len(calls), DR.RETRIES)
        self.assertIn("connection reset", str(ctx.exception))

    def test_bad_answer_is_not_retried(self):
        calls = []

        def one_shot(req, timeout=10):
            calls.append(1)
            return _ctx(b"<html>err</html>")

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(_netproxy, "urlopen", one_shot):
                with self.assertRaises(IOError):
                    DR.fetch_3dep((0.0, 0.0, 20.0, 20.0), 10.0, os.path.join(tmp, "t.tif"))
        self.assertEqual(len(calls), 1, "a deterministic bad answer must not be retried")


class UrlContract(unittest.TestCase):
    def test_url_asks_for_image_tiff_in_the_grid_crs(self):
        seen = {}

        def grab(req, timeout=10):
            seen["url"] = req.full_url
            return _ctx(tiny_tiff())

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(_netproxy, "urlopen", grab):
                DR.fetch_3dep((10.0, 20.0, 30.0, 40.0), 10.0, os.path.join(tmp, "t.tif"), crs=26914)
        url = seen["url"]
        self.assertIn(DR.EXPORT_URL, url)
        for needle in ("f=image", "format=tiff", "pixelType=F32", "bboxSR=26914",
                       "imageSR=26914", "size=2%2C2"):
            self.assertIn(needle, url, needle)

    def test_wgs84_crs_resolves_to_epsg(self):
        seen = {}

        def grab(req, timeout=10):
            seen["url"] = req.full_url
            return _ctx(tiny_tiff())

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(_netproxy, "urlopen", grab):
                DR.fetch_3dep((10.0, 20.0, 30.0, 40.0), 10.0, os.path.join(tmp, "t.tif"), crs="EPSG:26914")
        self.assertIn("bboxSR=26914", seen["url"])

    def test_oversize_box_refused_before_any_request(self):
        with self.assertRaises(ValueError):
            DR.fetch_3dep((0.0, 0.0, 50000.0, 50000.0), 10.0, "/tmp/never.tif")


# -- helpers ------------------------------------------------------------------
class _ctx(object):
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _one_shot(body):
    state = {"n": 0}

    def opener(req, timeout=10):
        state["n"] += 1
        return _ctx(body)
    return opener


if __name__ == "__main__":
    unittest.main()
