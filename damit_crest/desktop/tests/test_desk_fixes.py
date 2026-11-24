"""The 2026-11-20 desk fixes: real receptors for Classify, browser-mode DEM picker and Save, Cancel and a time limit
for the plugin buttons, the live log, Finder's known dams, and the Linux launcher. Headless: the fake qgis_process
from test_algorithms, fake HTTP answers, no network.

    python3 app/desktop/tests/test_desk_fixes.py
"""

from __future__ import annotations

import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import damit_desktop.qgis_run as qr  # noqa: E402
from damit_desktop import browser_io, real_receptors as rr  # noqa: E402
from damit_desktop.receptors import write_receptor_layers  # noqa: E402
from test_algorithms import ANALYSIS, DAM, PAYLOAD, Base  # noqa: E402

REPO = HERE.parents[2]


def geotiff(path: Path, epsg: int, origin=(-107910.0, 2668410.0), cell=30.0, size=(870, 499)) -> Path:
    """A minimal little-endian GeoTIFF header (no pixel data): enough for real_receptors.geotiff_info."""
    entries = []
    extra = b""
    base = 8 + 2 + 12 * 6 + 4

    def add(tag, typ, values, fmt):
        nonlocal extra
        data = struct.pack("<" + fmt * len(values), *values)
        if len(data) <= 4:
            entries.append(struct.pack("<HHI", tag, typ, len(values)) + data.ljust(4, b"\0"))
        else:
            entries.append(struct.pack("<HHII", tag, typ, len(values), base + len(extra)))
            extra += data

    add(256, 4, [size[0]], "I")
    add(257, 4, [size[1]], "I")
    add(33550, 12, [cell, cell, 0.0], "d")
    add(33922, 12, [0.0, 0.0, 0.0, origin[0], origin[1], 0.0], "d")
    geographic = epsg in (4326, 4269)
    keys = [1, 1, 0, 2, 1024, 0, 1, 2 if geographic else 1, (2048 if geographic else 3072), 0, 1, epsg]
    add(34735, 3, keys, "H")
    add(339, 3, [1], "H")  # SampleFormat, ignored
    body = struct.pack("<2sHI", b"II", 42, 8) + struct.pack("<H", len(entries)) + b"".join(entries) + struct.pack("<I", 0)
    path.write_bytes(body + extra)
    return path


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(routes: dict):
    """A urlopen stand-in: the first route whose key is in the URL answers (a dict as JSON, a str as is, an
    Exception is raised). Every URL asked is kept in .asked."""
    asked = []

    def opener(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        asked.append(url)
        for key, answer in routes.items():
            if key in url:
                if callable(answer):
                    answer = answer(url)
                if isinstance(answer, Exception):
                    raise answer
                body = answer if isinstance(answer, str) else json.dumps(answer)
                return FakeResponse(body.encode())
        raise OSError(f"no route for {url}")

    opener.asked = asked
    return opener


def line(coords, **props):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": props}


def point(x, y, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]}, "properties": props}


BBOX = (-97.4123, 46.8640, -97.0686, 47.0023)
BNSF = line([[-97.30, 46.95], [-97.20, 46.94]], RROWNER1="BNSF", SUBDIV="KO", NET="M")


class RasterAreaTests(unittest.TestCase):
    def test_albers_raster_area_matches_gdal(self):
        # ND00199's LISFLOOD hmax_ft.tif (EPSG:5070, 30 m, 870 x 499): gdalinfo's wgs84Extent
        # -97.4123324, 46.8640185 .. -97.0685646, 47.0023349.
        with tempfile.TemporaryDirectory() as d:
            box = rr.raster_bbox(geotiff(Path(d) / "hmax.tif", 5070))
        self.assertIsNotNone(box)
        for got, want in zip(box, (-97.4123324, 46.8640185, -97.0685646, 47.0023349)):
            self.assertAlmostEqual(got, want, places=5)

    def test_utm_and_web_mercator_match_proj(self):
        # pyproj (PROJ 9) answers for the same points.
        lon, lat = rr.to_lonlat(26914, 612345, 5212345)
        self.assertAlmostEqual(lon, -97.520741597, places=6)
        self.assertAlmostEqual(lat, 47.055064739, places=6)
        lon, lat = rr.to_lonlat(3857, -10840000, 5930000)
        self.assertAlmostEqual(lon, -97.377376799, places=6)
        self.assertAlmostEqual(lat, 46.925977040, places=6)

    def test_unknown_crs_or_not_a_tiff_gives_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(rr.raster_bbox(geotiff(Path(d) / "x.tif", 2265)))  # ND state plane ft: not known here
            junk = Path(d) / "junk.tif"
            junk.write_bytes(b"not a raster")
            self.assertIsNone(rr.raster_bbox(junk))

    def test_dam_box_uses_the_reach(self):
        box = rr.dam_bbox({"lon": -97.39, "lat": 46.98}, {"flood": {"lengthM": 23400}})
        self.assertAlmostEqual(box[3] - 46.98, 23.4 / 111.32, places=4)


class FindReceptorsTests(unittest.TestCase):
    def routes(self, **over):
        r = {
            "fragis.fra.dot.gov": "<html>Application Error</html>",
            "NTAD_North_American_Rail_Network": {"type": "FeatureCollection", "features": [BNSF]},
            "NorthDakota_2018_PR": {"type": "FeatureCollection", "features": [line([[-97.3, 46.9], [-97.2, 46.9]], aadt=320)]},
            "nsiapi": {"type": "FeatureCollection", "features": [point(-97.3, 46.95, fd_id=1, occtype="RES1-1SNB")]},
        }
        r.update(over)
        return r

    def test_online_layers_and_the_rail_fallback(self):
        opener = opener_for(self.routes())
        found = rr.find_receptors(BBOX, "ND", None, lambda s: None, offline=False, opener=opener)
        self.assertEqual(found["missing"], {})
        self.assertEqual(len(found["layers"]["RAIL"]), 1)
        self.assertIn("BTS", found["sources"]["RAIL"])  # FRA answered HTML, so the BTS copy was used
        self.assertIn("HPMS", found["sources"]["ROADS"])
        self.assertIn("NSI", found["sources"]["STRUCTURES"])
        hpms = [u for u in opener.asked if "NorthDakota_2018_PR" in u][0]
        self.assertIn("outFields=%2A", hpms)  # the service's field names are lower case; AADT in upper case is a 500

    def test_paging_follows_exceeded_transfer_limit(self):
        pages = []

        def rail(url):
            pages.append(url)
            more = len(pages) == 1
            return {"type": "FeatureCollection", "properties": {"exceededTransferLimit": more}, "features": [BNSF]}

        opener = opener_for(self.routes(**{"fragis.fra.dot.gov": rail}))
        found = rr.find_receptors(BBOX, "ND", None, lambda s: None, offline=False, opener=opener)
        self.assertEqual(len(found["layers"]["RAIL"]), 2)
        self.assertIn("resultOffset=1", pages[1])
        self.assertIn("FRA", found["sources"]["RAIL"])

    def test_a_failed_layer_is_missing_not_empty(self):
        opener = opener_for(self.routes(nsiapi=OSError("timed out")))
        found = rr.find_receptors(BBOX, "ND", None, lambda s: None, offline=False, opener=opener)
        self.assertIn("STRUCTURES", found["missing"])
        self.assertIn("timed out", found["missing"]["STRUCTURES"])
        self.assertNotIn("STRUCTURES", found["layers"])

    def test_offline_uses_the_data_folder_clipped_to_the_area(self):
        with tempfile.TemporaryDirectory() as d:
            rail = Path(d) / "ND" / "fra_rail"
            rail.mkdir(parents=True)
            far = line([[-100.0, 48.0], [-100.1, 48.1]], SUBDIV="FAR")
            (rail / "fra_rail.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [BNSF, far]}))
            found = rr.find_receptors(BBOX, "ND", d, lambda s: None, offline=True, opener=opener_for({}))
        self.assertEqual([f["properties"]["SUBDIV"] for f in found["layers"]["RAIL"]], ["KO"])
        self.assertIn("DamIT data folder", found["sources"]["RAIL"])
        self.assertEqual(set(found["missing"]), {"STRUCTURES", "ROADS"})
        self.assertIn("DAMIT_OFFLINE", found["missing"]["ROADS"])


class MergeTests(unittest.TestCase):
    def test_real_layers_replace_desk_valley_seeds_and_keep_mapped_ones(self):
        real = {"layers": {"RAIL": [BNSF], "STRUCTURES": [point(-97.3, 46.95, fd_id=7)], "ROADS": []},
                "sources": {"RAIL": "BTS", "STRUCTURES": "NSI", "ROADS": "HPMS"}, "missing": {}}
        with tempfile.TemporaryDirectory() as d:
            written = write_receptor_layers(Path(d), DAM, PAYLOAD, real=real)
            structures = json.loads(Path(written["layers"]["STRUCTURES"]).read_text())["features"]
            manifest = json.loads(Path(written["manifest"]).read_text())
        placed = [f["properties"]["placed"] for f in structures]
        self.assertEqual(sorted(placed), ["mapped", "real layer"])  # the desk-valley mobile home is gone
        self.assertEqual(written["counts"]["RAIL"], 1)
        self.assertNotIn("ROADS", written["counts"])  # the desk-valley road was replaced by HPMS, which had none here
        self.assertEqual(manifest["layerSources"]["RAIL"], "BTS")
        self.assertEqual(manifest["notChecked"], {})

    def test_without_real_layers_the_desk_payload_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            written = write_receptor_layers(Path(d), DAM, PAYLOAD)
        self.assertEqual(written["counts"], {"STRUCTURES": 2, "ROADS": 1})
        self.assertEqual(written["missing"], {})


class ClassifyRealReceptorTests(Base):
    def classify_run(self) -> str:
        return [line for line in self.calls_text().splitlines() if line.startswith("run ")][0]

    def depth(self) -> str:
        return str(geotiff(self.root / "hmax_ft.tif", 5070))

    def run_with(self, found, **extra):
        dam = {**DAM, "nid": "ND00199", "depthRaster": self.depth(),
               "classification": {"mode": "preset", "preset": "ND", "presetLabel": "North Dakota"}, **extra}
        calls = []

        def fake(bbox, state, data, log, cancel=None):
            calls.append((bbox, state))
            return found

        with mock.patch.object(qr, "REAL_RECEPTORS", fake):
            result = qr.run_classify(dam, ANALYSIS, str(self.root / "work"), self.log, receptors=PAYLOAD)
        return result, calls

    def test_classify_sends_the_rail_line_and_is_complete(self):
        found = {"layers": {"RAIL": [BNSF], "STRUCTURES": [point(-97.3, 46.95)], "ROADS": [line([[-97.3, 46.9], [-97.2, 46.9]], aadt=40)]},
                 "sources": {"RAIL": "BTS NTAD (online)", "STRUCTURES": "NSI (online)", "ROADS": "HPMS (online)"}, "missing": {}}
        result, calls = self.run_with(found)
        self.assertTrue(result["ok"], self.lines)
        self.assertEqual(calls[0][1], "ND")
        for got, want in zip(calls[0][0], (-97.4123324, 46.8640185, -97.0685646, 47.0023349)):
            self.assertAlmostEqual(got, want, places=5)  # the depth raster's own area
        run = self.classify_run()
        self.assertIn("--RAIL=", run)
        c = result["classification"]
        self.assertTrue(c["complete"])
        self.assertEqual(c["notChecked"], {})
        self.assertEqual(c["layerSources"]["RAIL"], "BTS NTAD (online)")
        self.assertNotIn("incomplete", result)
        text = "\n".join(self.lines)
        self.assertIn("Rail: 1 line(s) in the area", text)  # no trains lookup given: says M9a stops at Medium
        self.assertNotIn("INCOMPLETE", text)

    def test_the_rail_lookup_field_is_sent(self):
        lookup = self.root / "trains.csv"
        lookup.write_text("field,value,trains_per_day,source\nSUBDIV,KO,15,needs a ruling\n", encoding="utf-8")
        found = {"layers": {"RAIL": [BNSF]}, "sources": {"RAIL": "x", "STRUCTURES": "x", "ROADS": "x"}, "missing": {}}
        result, _ = self.run_with(found, railTrainsLookup=str(lookup))
        self.assertIn("--RAIL_TRAINS_LOOKUP=" + str(lookup.resolve()), self.classify_run())
        self.assertEqual(result["classification"]["railTrainsLookup"], str(lookup.resolve()))
        self.assertNotIn("Rail: 1 line(s)", "\n".join(self.lines))

    def test_unchecked_layers_make_the_class_incomplete_and_say_so(self):
        found = {"layers": {}, "sources": {}, "missing": {"RAIL": "offline", "ROADS": "offline", "STRUCTURES": "offline"}}
        result, _ = self.run_with(found)
        self.assertTrue(result["ok"], self.lines)  # the desk's own receptors still go
        self.assertTrue(result["incomplete"])
        c = result["classification"]
        self.assertFalse(c["complete"])
        self.assertEqual(set(c["notChecked"]), {"RAIL", "ROADS", "STRUCTURES"})
        text = "\n".join(self.lines)
        self.assertIn("rail NOT CHECKED", text)
        self.assertIn("INCOMPLETE: Significant is at least the class", text)

    def test_offline_without_a_data_folder_is_incomplete(self):
        dam = {**DAM, "depthRaster": self.depth(),
               "classification": {"mode": "preset", "preset": "ND", "presetLabel": "North Dakota"}}
        result = qr.run_classify(dam, ANALYSIS, str(self.root / "work"), self.log, receptors=PAYLOAD)
        self.assertTrue(result.get("incomplete"), self.lines)


class LiveLogAndCancelTests(Base):
    def script(self, body: str) -> list[str]:
        path = self.root / "slow.py"
        path.write_text(body, encoding="utf-8")
        return [sys.executable, "-u", str(path)]

    def test_lines_reach_the_log_while_the_program_runs(self):
        cmd = self.script("import time\nprint('first line', flush=True)\ntime.sleep(3)\nprint('last line')\n")
        seen_at = {}
        start = time.monotonic()

        def log(line):
            seen_at.setdefault(str(line), time.monotonic() - start)

        code, text = qr._run_logged(cmd, log, timeout=30)
        self.assertEqual(code, 0)
        self.assertLess(seen_at["first line"], 2.5, "the first line must arrive before the program ends")
        self.assertIn("last line", seen_at)
        self.assertIn("first line", text)

    def test_cancel_stops_a_plugin_job_and_its_children(self):
        child_pid = self.root / "child.pid"
        cmd = self.script(
            "import subprocess, sys, time\n"
            f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(child_pid)!r}, 'w').write(str(p.pid))\n"
            "print('started', flush=True)\n"
            "time.sleep(60)\n")
        cancel = threading.Event()
        threading.Timer(1.5, cancel.set).start()
        start = time.monotonic()
        code, text = qr._run_logged(cmd, lambda s: None, timeout=None, cancel=cancel)
        self.assertEqual(code, qr.STOPPED_CANCEL)
        self.assertLess(time.monotonic() - start, 20)
        self.assertIn("cancelled in DamIT Desk", text)
        if os.name == "posix":
            pid = int(child_pid.read_text())
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
                alive = Path(f"/proc/{pid}/stat").is_file() and " Z " not in Path(f"/proc/{pid}/stat").read_text()
            except OSError:
                alive = False
            self.assertFalse(alive, "the child of the cancelled program must be stopped too")

    def test_pmp_honours_cancel(self):
        cancel = threading.Event()
        cancel.set()
        slow = self.root / "qgis_slow"
        slow.write_text("#!/usr/bin/env python3\nimport sys, time\nif sys.argv[1] == 'help':\n"
                        "    print('POINT: p'); print('OUTPUT_CSV: c'); print('OUTPUT_JSON: j'); sys.exit(0)\n"
                        "time.sleep(60)\n", encoding="utf-8")
        slow.chmod(0o755)
        if os.name == "nt":
            self.skipTest("the slow fake is a shebang script")
        with mock.patch.dict(os.environ, {"QGIS_PROCESS": str(slow)}):
            qr._ENUM_HELP.clear()
            start = time.monotonic()
            result = qr.run_pmp(DAM, ANALYSIS, str(self.root / "work"), self.log, cancel=cancel)
        self.assertLess(time.monotonic() - start, 20)
        self.assertTrue(result.get("cancelled"), self.lines)
        self.assertIn("was cancelled", "\n".join(self.lines))

    def test_plugin_time_limits(self):
        self.assertEqual(qr.plugin_timeout("pmp", {}), 900.0)
        self.assertEqual(qr.plugin_timeout("data", {}), 3 * 3600.0)
        self.assertEqual(qr.plugin_timeout("finder", {"DAMIT_PLUGIN_TIMEOUT_S": "60"}), 60.0)
        self.assertIsNone(qr.plugin_timeout("data", {"DAMIT_PLUGIN_TIMEOUT_S": "0"}))

    def test_start_job_passes_cancel_to_the_plugin_buttons(self):
        import damit_desktop.__main__ as m

        got = {}

        def fake(dam, analysis, work, log, files=None, config=None, cancel=None):
            got["cancel"] = cancel
            return {"ok": True}

        for kind, name in (("data", "run_data"), ("pmp", "run_pmp"), ("finder", "run_finder")):
            got.clear()
            with mock.patch.object(m, name, fake):
                job = m.start_job(kind, DAM, ANALYSIS, None)
                for _ in range(50):
                    if (m.job_snapshot(job["id"]) or {}).get("done"):
                        break
                    time.sleep(0.05)
            self.assertIsInstance(got.get("cancel"), threading.Event, kind)


class FinderKnownDamsTests(Base):
    def test_known_dams_carry_the_nid_list_and_this_dam(self):
        bundle = {"cols": ["nid", "name", "lat", "lon"], "rows": [["ND00199", "Swan Buffalo 12", 46.98337, -97.39113],
                                                                 ["ND00200", "Other", 46.9, -97.3], ["ND00201", "No point", None, None]]}
        path = self.root / "known.geojson"
        dam = {**DAM, "nid": "ND00199", "lon": -97.39113, "lat": 46.98337}
        out = qr.write_known_dams(path, dam, self.log, load_state=lambda state: bundle)
        feats = json.loads(Path(out).read_text())["features"]
        self.assertEqual(sorted(f["properties"]["nid"] for f in feats), ["ND00199", "ND00200"])

    def test_this_dam_alone_when_there_is_no_nid_list(self):
        def boom(state):
            raise RuntimeError("no network")

        out = qr.write_known_dams(self.root / "k.geojson", DAM, self.log, load_state=boom)
        feats = json.loads(Path(out).read_text())["features"]
        self.assertEqual([f["properties"]["source"] for f in feats], ["desk record"])
        self.assertIn("this dam only", "\n".join(self.lines))

    def test_finder_sends_known(self):
        dem = self.root / "dem.tif"
        dem.write_bytes(b"x")
        qr.run_finder({**DAM, "demPath": str(dem)}, ANALYSIS, str(self.root / "work"), self.log)
        run = [l for l in self.calls_text().splitlines() if l.startswith("run damit_find:embankments")][0]
        self.assertIn("--KNOWN=", run)


class BrowserIoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.settings = self.root / "settings.json"
        self.env = mock.patch.dict(os.environ, {"DAMIT_WORK": str(self.work), "HOME": str(self.root),
                                                "DAMIT_DATA": "", "DAMIT_DEM": "", "DAMIT_DEM_ROOTS": "",
                                                "DAMIT_WORK_ROOTS": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_list_shows_folders_and_dem_files_only(self):
        dems = self.work / "dems"
        dems.mkdir()
        (dems / "a.vrt").write_text("x")
        (dems / "notes.txt").write_text("x")
        (dems / ".hidden.tif").write_text("x")
        (dems / "sub").mkdir()
        listing = browser_io.list_dir(str(dems), "dem", self.settings)
        self.assertEqual([(e["name"], e["dir"]) for e in listing["entries"]], [("sub", True), ("a.vrt", False)])
        self.assertEqual(listing["parent"], str(self.work))
        folders = browser_io.list_dir(str(dems), "folder", self.settings)
        self.assertEqual([e["name"] for e in folders["entries"]], ["sub"])
        with self.assertRaises(browser_io.BrowserIOError):
            browser_io.list_dir(str(self.work / "nope"), "dem", self.settings)

    def test_list_starts_in_the_work_folder_and_stops_at_its_roots(self):
        listing = browser_io.list_dir(None, "dem", self.settings)
        self.assertEqual(listing["dir"], str(self.work))
        self.assertIsNone(listing["parent"], "no Up out of the work folder")
        self.assertIn(str(self.work), listing["roots"])
        for outside in (str(self.root), "/", str(self.work / ".." / ".."), str(self.work) + "/../"):
            with self.subTest(outside=outside), self.assertRaises(browser_io.BrowserIOError):
                browser_io.list_dir(outside, "dem", self.settings)

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlink_out_of_the_roots_is_neither_listed_nor_followed(self):
        secret = self.root / "secret"
        secret.mkdir()
        (secret / "private.tif").write_text("x")
        (self.work / "escape").symlink_to(secret, target_is_directory=True)
        (self.work / "escape.tif").symlink_to(secret / "private.tif")
        (self.work / "inside").mkdir()
        (self.work / "ok.tif").symlink_to(self.work / "inside")
        names = [e["name"] for e in browser_io.list_dir(None, "dem", self.settings)["entries"]]
        self.assertNotIn("escape", names)
        self.assertNotIn("escape.tif", names)
        self.assertIn("inside", names)
        with self.assertRaises(browser_io.BrowserIOError):
            browser_io.list_dir(str(self.work / "escape"), "dem", self.settings)
        with self.assertRaises(browser_io.BrowserIOError):
            browser_io.choose_dem(self.settings, str(self.work / "escape.tif"))

    def test_choose_dem_is_the_native_pickers_setting(self):
        from damit_desktop import localdem

        dem = self.work / "Cass 10m.vrt"
        dem.write_text("x")
        out = browser_io.choose_dem(self.settings, str(dem))
        self.assertEqual(out["path"], str(dem))
        self.assertEqual(localdem.read_dem_path(self.settings), str(dem))
        for bad in ("", "relative.tif", str(self.work / "missing.tif"), str(self.settings)):
            with self.assertRaises(browser_io.BrowserIOError):
                browser_io.choose_dem(self.settings, bad)
        browser_io.clear_dem(self.settings)
        self.assertIsNone(localdem.read_dem_path(self.settings))

    def test_a_dem_outside_needs_dem_roots(self):
        other = self.root / "dems"
        other.mkdir()
        dem = other / "cass.vrt"
        dem.write_text("x")
        with self.assertRaises(browser_io.BrowserIOError) as cm:
            browser_io.choose_dem(self.settings, str(dem))
        self.assertIn("DAMIT_DEM_ROOTS", str(cm.exception))
        with mock.patch.dict(os.environ, {"DAMIT_DEM_ROOTS": str(other)}):
            self.assertEqual(browser_io.choose_dem(self.settings, str(dem))["path"], str(dem))
            self.assertIn(str(other), browser_io.list_dir(None, "dem", self.settings)["roots"])
        # The chosen DEM's folder stays readable (the picker opens there next time).
        self.assertIn(other, browser_io.read_roots(self.settings))

    def test_save_goes_to_the_exports_folder_and_never_overwrites(self):
        first = browser_io.save_export(self.settings, "../../report.csv", b"a,b\n")
        second = browser_io.save_export(self.settings, "report.csv", b"c,d\n")
        self.assertEqual(first, self.work / "exports" / "report.csv")
        self.assertEqual(second.name, "report (2).csv")
        self.assertEqual(first.read_bytes(), b"a,b\n")
        other = self.work / "elsewhere"
        other.mkdir()
        browser_io.set_export_dir(self.settings, str(other))
        self.assertEqual(browser_io.save_export(self.settings, "x.json", b"{}").parent, other)
        with self.assertRaises(browser_io.BrowserIOError):
            browser_io.set_export_dir(self.settings, str(self.work / "missing"))

    def test_file_names_cannot_name_a_folder(self):
        for name, want in (("..\\..\\evil.csv", "evil.csv"), ("/etc/passwd", "passwd"), ("..", "damit_export.txt"),
                           ("a\x00b:c?.txt", "a_b_c_.txt"), (".bashrc", "bashrc"), ("", "damit_export.txt")):
            with self.subTest(name=name):
                self.assertEqual(browser_io.safe_name(name), want)
                saved = browser_io.save_export(self.settings, name, b"x")
                self.assertEqual(saved.parent, self.work / "exports")
        self.assertFalse((self.root / "evil.csv").exists())

    def test_exports_must_stay_in_the_work_folder(self):
        outside = self.root / "outside"
        outside.mkdir()
        with self.assertRaises(browser_io.BrowserIOError):
            browser_io.set_export_dir(self.settings, str(outside))
        with self.assertRaises(browser_io.BrowserIOError):
            browser_io.set_export_dir(self.settings, str(self.work / ".." / "outside"))
        # A settings file edited by hand to point outside is ignored: Save falls back to <work>/exports.
        self.settings.write_text(json.dumps({"export_dir": str(outside)}))
        self.assertEqual(browser_io.save_export(self.settings, "a.txt", b"x").parent, self.work / "exports")
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_save_does_not_follow_a_symlink_out(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.work / "exports").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(browser_io.BrowserIOError):
            browser_io.save_export(self.settings, "a.txt", b"x")
        self.assertEqual(list(outside.iterdir()), [])
        (self.work / "exports").unlink()
        (self.work / "exports").mkdir()
        victim = self.root / "victim.txt"
        victim.write_text("keep")
        (self.work / "exports" / "b.txt.part").symlink_to(victim)
        with self.assertRaises(browser_io.BrowserIOError):
            browser_io.save_export(self.settings, "b.txt", b"overwrite")
        self.assertEqual(victim.read_text(), "keep")


class BrowserApiTests(unittest.TestCase):
    """The browser-mode endpoints behind the token check."""

    @classmethod
    def setUpClass(cls):
        import damit_desktop.__main__ as m

        cls.m = m
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve()
        cls.env = mock.patch.dict(os.environ, {"HOME": str(cls.root), "DAMIT_WORK": str(cls.root / "work"),
                                               "DAMIT_DATA": "", "DAMIT_DEM": "", "DAMIT_DEM_ROOTS": "",
                                               "DAMIT_WORK_ROOTS": ""})
        cls.env.start()
        cls.saved = m.SETTINGS_FILE
        m.SETTINGS_FILE = cls.root / "settings.json"
        web = cls.root / "web"
        web.mkdir()
        (web / "index.html").write_text("<html><head></head></html>")
        cls.server = m.serve(web, port=0)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.m.SETTINGS_FILE = cls.saved
        cls.env.stop()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, token=True):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            h[self.m.TOKEN_HEADER] = self.m.API_TOKEN
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, json.loads(data or b"null")

    def test_token_is_required(self):
        self.assertEqual(self.req("GET", "/api/fs/list", token=False)[0], 403)
        self.assertEqual(self.req("POST", "/api/save", {"name": "a.txt", "text": "x"}, token=False)[0], 403)

    def test_page_has_no_token_and_outside_folders_are_refused(self):
        import http.client
        from urllib.parse import quote

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/index.html", headers={"Host": f"127.0.0.1:{self.port}"})
        page = conn.getresponse().read()
        conn.close()
        self.assertNotIn(self.m.API_TOKEN.encode(), page)
        for bad in ("/", str(self.root), str(self.root / "work" / ".." / "..")):
            with self.subTest(dir=bad):
                status, body = self.req("GET", f"/api/fs/list?dir={quote(bad)}&mode=dem")
                self.assertEqual(status, 400, body)
        secret = self.root / "secret.tif"
        secret.write_bytes(b"x")
        self.assertEqual(self.req("POST", "/api/dem/choose", {"path": str(secret)})[0], 400)
        self.assertEqual(self.req("POST", "/api/export_dir", {"path": str(self.root)})[0], 400)
        status, saved = self.req("POST", "/api/save", {"name": "../../../escape.txt", "text": "x"})
        self.assertEqual(status, 200)
        self.assertEqual(Path(saved["saved"]).parent, (self.root / "work" / "exports").resolve())

    def test_pick_a_dem_and_save_through_the_server(self):
        (self.root / "work").mkdir(exist_ok=True)
        dem = self.root / "work" / "dem.tif"
        dem.write_bytes(b"x")
        status, listing = self.req("GET", f"/api/fs/list?dir={self.root / 'work'}&mode=dem")
        self.assertEqual(status, 200)
        self.assertIn("dem.tif", [e["name"] for e in listing["entries"]])
        status, chosen = self.req("POST", "/api/dem/choose", {"path": str(dem)})
        self.assertEqual((status, chosen["path"]), (200, str(dem)))
        self.assertEqual(self.req("GET", "/api/dem/choice")[1]["path"], str(dem))
        self.assertEqual(self.req("POST", "/api/dem/choose", {"path": "x.txt"})[0], 400)
        status, saved = self.req("POST", "/api/save", {"name": "dam.json", "text": "{}"})
        self.assertEqual(status, 200)
        self.assertEqual(Path(saved["saved"]).read_text(), "{}")
        status, saved = self.req("POST", "/api/save", {"name": "view.png", "b64": "iVBORw=="})
        self.assertEqual(status, 200)
        self.assertEqual(Path(saved["saved"]).read_bytes()[:4], b"\x89PNG")
        self.assertEqual(self.req("GET", "/api/export_dir")[1]["dir"], str((self.root / "work").resolve() / "exports"))


@unittest.skipIf(os.name == "nt" or shutil.which("sh") is None, "the Linux / Mac launcher is a shell script")
class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (REPO / "bin" / "install-launcher").is_file():
            raise unittest.SkipTest(
                "desk launchers live in the damit-desk repository, not this monorepo copy"
            )

    def test_linux_menu_entry_quotes_the_path_and_uses_the_icon_theme_folder(self):
        if sys.platform == "darwin":
            self.skipTest("Linux branch")
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            home.mkdir()
            env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": ""}
            subprocess.run(["sh", str(REPO / "bin" / "install-launcher")], env=env, check=True,
                           stdout=subprocess.DEVNULL)
            entry = (home / ".local/share/applications/damit-desk.desktop").read_text()
            self.assertTrue((home / ".local/share/icons/hicolor/scalable/apps/damit-desk.svg").is_file())
        exec_line = [l for l in entry.splitlines() if l.startswith("Exec=")][0]
        self.assertTrue(exec_line.startswith('Exec="'), exec_line)
        self.assertIn("Terminal=true", entry)  # the server's terminal: its URL, its log, Ctrl+C to stop
        self.assertTrue(exec_line.rstrip().endswith('" --profile us'), exec_line)

    def test_one_menu_entry_per_profile(self):
        if sys.platform == "darwin":
            self.skipTest("Linux branch")
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            home.mkdir()
            env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": ""}
            subprocess.run(["sh", str(REPO / "bin" / "install-launcher")], env=env, check=True,
                           stdout=subprocess.DEVNULL)
            apps = home / ".local/share/applications"
            us = (apps / "damit-desk.desktop").read_text()
            nd = (apps / "damit-desk-nd.desktop").read_text()
        self.assertIn("Name=DamIT Desk\n", us)
        self.assertIn("Name=DamIT Desk (North Dakota)\n", nd)
        self.assertIn("--profile nd", [l for l in nd.splitlines() if l.startswith("Exec=")][0])


class LauncherIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (REPO / "share" / "damit-desk.icns").is_file():
            raise unittest.SkipTest(
                "desk icons live in the damit-desk repository, not this monorepo copy"
            )

    """The app icon per OS: the SVG (Linux), the .icns the Mac app bundle names, the .ico the Windows shortcuts use."""

    def test_icns_holds_png_renders_at_every_size_the_mac_asks_for(self):
        data = (REPO / "share" / "damit-desk.icns").read_bytes()
        self.assertEqual(data[:4], b"icns")
        self.assertEqual(int.from_bytes(data[4:8], "big"), len(data))
        sizes, at = {}, 8
        while at < len(data):
            kind, length = data[at:at + 4].decode("ascii"), int.from_bytes(data[at + 4:at + 8], "big")
            png = data[at + 8:at + length]
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n", kind)
            sizes[kind] = int.from_bytes(png[16:20], "big")
            at += length
        self.assertEqual(at, len(data))
        for kind, px in (("icp4", 16), ("icp5", 32), ("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024)):
            self.assertEqual(sizes.get(kind), px, kind)

    def test_mac_bundle_and_windows_shortcuts_name_their_icon(self):
        sh = (REPO / "bin" / "install-launcher").read_text()
        self.assertIn("<key>CFBundleIconFile</key><string>damit-desk</string>", sh)
        self.assertIn('cp "$ICNS" "$DEST/Contents/Resources/damit-desk.icns"', sh)
        self.assertIn('mac_app "DamIT Desk (North Dakota)" damit-desk-nd nd', sh)
        ps1 = (REPO / "bin" / "install-launcher.ps1").read_text()
        self.assertIn('$Link.IconLocation = $Icon + ",0"', ps1)
        self.assertIn('@("DamIT Desk (North Dakota)", "nd")', ps1)
        ico = (REPO / "share" / "damit-desk.ico").read_bytes()
        self.assertEqual(ico[:4], b"\x00\x00\x01\x00")  # an icon resource
        self.assertGreaterEqual(int.from_bytes(ico[4:6], "little"), 4)


if __name__ == "__main__":
    unittest.main()


class SuiteQgisProcess(unittest.TestCase):
    def test_suite_wrapper_found_before_path(self):
        with tempfile.TemporaryDirectory() as d:
            name = "qgis-process-damit.cmd" if os.name == "nt" else "qgis-process-damit.sh"
            Path(d, name).write_text("#!/bin/sh\n")
            env = {"DAMSUITE_PREFIX": d, "QGIS_PROCESS": ""}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(qr.find_qgis_process(), str(Path(d, name)))
            with mock.patch.dict(os.environ, {**env, "QGIS_PROCESS": str(Path(d, name))}):
                self.assertEqual(qr.find_qgis_process(), str(Path(d, name)))
